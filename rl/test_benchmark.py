"""Accounting tests: uv run --with numpy python -m unittest rl.test_benchmark -v"""
from types import SimpleNamespace
import unittest

import numpy as np

from rl.benchmark import BenchmarkConfig, RandomFlippers, run_benchmark


class FakeClock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class FakeGame:
    def __init__(self, clock, **options):
        self.clock, self.options = clock, options
        self.clock.advance(.5)
        self.episode_steps, self.ticks = 0, 0
        self.engine_info = {"protocol": 2, "renderer": "fake", "gpu_vendor_id": 0}

    def observation(self):
        return SimpleNamespace(frame=np.zeros((64, 64, 3), dtype=np.uint8),
                               ticks=self.ticks, started=self.episode_steps > 0,
                               game_over=self.episode_steps == 2, score=self.episode_steps * 10)

    def step(self, action=None, *, physics_ticks=None):
        if self.episode_steps == 2:
            raise AssertionError("Benchmark stepped a terminal table instead of resetting")
        if physics_ticks == 0:
            self.clock.advance(.02)
        else:
            self.clock.advance(.01)
            self.episode_steps += 1
            self.ticks += self.options["physics_ticks"]
        return self.observation()

    def reset(self):
        self.clock.advance(1.0)
        self.episode_steps, self.ticks = 0, 0
        return self.observation()

    def __enter__(self): return self
    def __exit__(self, *_): pass


class BenchmarkTests(unittest.TestCase):
    def run_fake(self, config):
        clock = FakeClock()
        return run_benchmark(config, game_factory=lambda **opts: FakeGame(clock, **opts), clock=clock)

    def test_reset_time_included_without_counting_reset_frames_as_transitions(self):
        result = self.run_fake(BenchmarkConfig(64, 64, 16, seconds=.05, warmup_steps=0))
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["completed_episodes"], 1)
        self.assertEqual(result["resets"], 1)
        self.assertAlmostEqual(result["startup_seconds"], .52)
        self.assertAlmostEqual(result["step_call_seconds"], .02)
        self.assertAlmostEqual(result["reset_seconds"], 1.0)
        self.assertAlmostEqual(result["measured_seconds"], 1.02)
        self.assertAlmostEqual(result["step_calls_per_second"], 100)
        self.assertAlmostEqual(result["rollout_steps_per_second"], 2 / 1.02)
        self.assertAlmostEqual(result["latency_ms"]["p95"], 10)
        self.assertAlmostEqual(result["physics_ticks_per_second"], 32 / 1.02)
        self.assertEqual(result["completed_episode_scores"], [20])
        self.assertEqual(result["rgb_bytes_per_frame"], 64 * 64 * 3)

    def test_warmup_transitions_not_counted(self):
        result = self.run_fake(BenchmarkConfig(64, 64, 16, seconds=.005, warmup_steps=1))
        self.assertEqual(result["steps"], 1)
        self.assertAlmostEqual(result["warmup_seconds"], .01)
        self.assertEqual(result["resets"], 0)

    def test_warmup_resets_are_not_measured(self):
        result = self.run_fake(BenchmarkConfig(64, 64, 16, seconds=.005, warmup_steps=3))
        self.assertEqual(result["steps"], 1)
        self.assertAlmostEqual(result["warmup_seconds"], 1.03)
        self.assertEqual(result["resets"], 0)

    def test_action_policy_is_seeded_and_sticky_within_time_blocks(self):
        first, second = RandomFlippers(42), RandomFlippers(42)
        for ticks in (0, 16, 32, 112, 300, 2016):
            obs = SimpleNamespace(ticks=ticks)
            self.assertEqual(first.action(obs), second.action(obs))
        policy = RandomFlippers(0)
        self.assertEqual(policy.action(SimpleNamespace(ticks=0)), policy.action(SimpleNamespace(ticks=99)))

    def test_invalid_configs(self):
        for config in (BenchmarkConfig(physics_ticks=0), BenchmarkConfig(seconds=float("nan")),
                       BenchmarkConfig(seconds=0), BenchmarkConfig(warmup_steps=-1)):
            with self.assertRaises(ValueError): config.validate()


if __name__ == "__main__":
    unittest.main()
