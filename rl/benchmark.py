"""Single-environment rollout throughput, with actual RGB observations and resets."""
from dataclasses import asdict, dataclass
import math
import random
import time

import numpy as np

from .camera import Camera
from .client import Action, Pinball


@dataclass(frozen=True)
class BenchmarkConfig:
    width: int = 1344
    height: int = 760
    physics_ticks: int = 16
    seconds: float = 30.0
    warmup_steps: int = 100
    seed: int = 0

    def validate(self):
        for value in (self.width, self.height):
            if type(value) is not int or not 64 <= value <= 4096:
                raise ValueError("Resolution dimensions must be integers in 64..4096")
        if type(self.physics_ticks) is not int or not 1 <= self.physics_ticks <= 10000:
            raise ValueError("physics_ticks must be an integer in 1..10000")
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("seconds must be finite and positive")
        if type(self.warmup_steps) is not int or self.warmup_steps < 0:
            raise ValueError("warmup_steps must be a nonnegative integer")


class RandomFlippers:
    """Random flipper states held in 100ms simulated-time blocks, launch pulses.

    This is just an inexpensive workload, not an agent or a physics RNG seed.
    """
    def __init__(self, seed):
        self.random = random.Random(seed)
        self.new_episode()

    def new_episode(self):
        self.bucket = -1
        self.left = self.right = False

    def action(self, observation):
        bucket = observation.ticks // 100
        while self.bucket < bucket:
            self.left = bool(self.random.getrandbits(1))
            self.right = bool(self.random.getrandbits(1))
            self.bucket += 1
        return Action(self.left, self.right, (observation.ticks // 2000) % 2 == 0)


def run_benchmark(config, *, camera=True, engine=None, table=None, backend="Vulkan",
                  timeout=60.0, game_factory=Pinball, clock=time.perf_counter):
    """Time active episodes only; terminal observations trigger in-process game resets.

    Cold startup/warmup/last shutdown are excluded from rollout time. Resets during
    measurement are included, even if one crosses the requested time budget.
    game_factory/clock injection is for accounting tests without launching VPX.
    """
    config.validate()
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    options = dict(width=config.width, height=config.height, physics_ticks=config.physics_ticks,
                   headless=True, backend=backend, timeout=timeout,
                   camera=Camera() if camera else None)
    if engine is not None:
        options["engine"] = engine
    if table is not None:
        options["table"] = table
    policy = RandomFlippers(config.seed)
    startup_begin = clock()
    with game_factory(**options) as game:
        obs = game.step(physics_ticks=0)
        startup_seconds = clock() - startup_begin
        warmup_begin = clock()
        for _ in range(config.warmup_steps):
            if obs.game_over:
                obs = game.reset()
                policy.new_episode()
            obs = game.step(policy.action(obs))
        warmup_seconds = clock() - warmup_begin

        step_times, reset_times = [], []
        completed_scores = []
        frame_bytes = obs.frame.nbytes
        begin = clock()
        while clock() - begin < config.seconds:
            if obs.game_over:
                reset_begin = clock()
                obs = game.reset()
                reset_times.append(clock() - reset_begin)
                policy.new_episode()
                if clock() - begin >= config.seconds:
                    break
            action = policy.action(obs)
            step_begin = clock()
            obs = game.step(action)
            step_times.append(clock() - step_begin)
            if obs.game_over:
                completed_scores.append(obs.score)
        elapsed = clock() - begin
        engine_info = dict(game.engine_info)

    steps = len(step_times)
    step_seconds = sum(step_times)
    reset_seconds = sum(reset_times)
    rate = steps / elapsed if elapsed else 0.0
    latencies = np.asarray(step_times) * 1000
    return dict(
        config=asdict(config), camera="physical" if camera else "table",
        camera_settings=asdict(Camera()) if camera else None, engine_info=engine_info,
        startup_seconds=startup_seconds, warmup_seconds=warmup_seconds,
        measured_seconds=elapsed, steps=steps,
        step_call_seconds=step_seconds, reset_seconds=reset_seconds,
        resets=len(reset_times), completed_episodes=len(completed_scores),
        completed_episode_scores=completed_scores,
        rollout_steps_per_second=rate,
        step_calls_per_second=steps / step_seconds if step_seconds else 0.0,
        latency_ms=dict(mean=float(latencies.mean()), p50=float(np.percentile(latencies, 50)),
                        p95=float(np.percentile(latencies, 95)), p99=float(np.percentile(latencies, 99)))
        if steps else None,
        mean_reset_seconds=reset_seconds / len(reset_times) if reset_times else None,
        reset_fraction=reset_seconds / elapsed if elapsed else 0.0,
        physics_ticks_per_second=rate * config.physics_ticks,
        simulated_seconds_per_wall_second=rate * config.physics_ticks / 1000,
        transitions_per_hour=rate * 3600,
        seconds_per_million_transitions=1e6 / rate if rate else None,
        rgb_bytes_per_frame=frame_bytes,
        rgb_mib_per_second=rate * frame_bytes / (1024 ** 2),
        raw_rgb_gb_per_hour=rate * 3600 * frame_bytes / 1e9,
    )
