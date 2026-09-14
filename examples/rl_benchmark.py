# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy>=1.26"]
# ///
"""uv run examples/rl_benchmark.py --seconds 30 --output /tmp/vpx-benchmark.json"""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rl.benchmark import BenchmarkConfig, run_benchmark


def resolution(value):
    try:
        w, h = (int(part) for part in value.lower().split("x"))
        BenchmarkConfig(width=w, height=h).validate()
        return w, h
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use WIDTHxHEIGHT, each dimension 64..4096") from exc


def command_output(command):
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolutions", type=resolution, nargs="+", default=[(1344, 760), (672, 380), (336, 190)])
    parser.add_argument("--ticks", type=int, nargs="+", default=[16], help="Exact physics ticks per observed transition")
    parser.add_argument("--seconds", type=float, default=30, help="Measured wall seconds per configuration, including resets")
    parser.add_argument("--warmup-steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0, help="Action workload seed, NOT an engine physics seed")
    parser.add_argument("--camera", choices=["physical", "table"], default="physical")
    parser.add_argument("--backend", choices=["Vulkan", "OpenGL"], default="Vulkan")
    parser.add_argument("--engine", type=Path, default=ROOT / "build/VPinballX_BGFX")
    parser.add_argument("--table", type=Path, default=ROOT / "rl/assets/rl_table.vpx")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--output", type=Path, help="JSON report (rewritten after each completed configuration)")
    args = parser.parse_args()
    configs = [BenchmarkConfig(w, h, ticks, args.seconds, args.warmup_steps, args.seed)
               for w, h in args.resolutions for ticks in args.ticks]
    for config in configs:
        try:
            config.validate()
        except ValueError as exc:
            parser.error(str(exc))
    for path in (args.engine, args.table):
        if not path.is_file():
            parser.error(f"File not found: {path}")
    report = dict(
        schema_version=1, timestamp_utc=datetime.now(timezone.utc).isoformat(),
        platform=platform.platform(), python=platform.python_version(),
        git_commit=command_output(["git", "rev-parse", "HEAD"]),
        tracked_changes=command_output(["git", "status", "--porcelain", "--untracked-files=no"]),
        gpu=command_output(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]),
        engine_sha256=sha256(args.engine), table_sha256=sha256(args.table),
        policy="random flippers in 100ms simulation blocks; 2s launch pulses",
        workers=1, results=[],
    )
    print("Single headless environment; no viewer, pacing, agent inference or disk frame writes.")
    print("A step = one action + N physics ticks + one RGB observation. Resets start new games in the same process.")
    print("GPU:", report["gpu"] or "See per-run engine_info in JSON", flush=True)
    for config in configs:
        print(f"\n{config.width}x{config.height}, {config.physics_ticks} ticks/step; "
              f"warming up {config.warmup_steps} steps, then measuring {config.seconds:g}s...", flush=True)
        result = run_benchmark(config, camera=args.camera == "physical", engine=args.engine,
                               table=args.table, backend=args.backend, timeout=args.timeout)
        report["results"].append(result)
        info = result["engine_info"]
        print(f"  {info['renderer']} / GPU vendor {info['gpu_vendor_id']:#06x}, device {info['gpu_device_id']:#06x}")
        if info["gpu_vendor_id"] != 0x10DE:
            print("  WARNING: engine is not reporting an NVIDIA GPU", file=sys.stderr)
        print(f"  Rollout: {result['rollout_steps_per_second']:.1f} steps/s including resets "
              f"({result['transitions_per_hour']:,.0f} transitions/hour)")
        print(f"  Step calls only: {result['step_calls_per_second']:.1f}/s; "
              f"simulation {result['simulated_seconds_per_wall_second']:.2f}x realtime including resets")
        if result["latency_ms"]:
            latency = result["latency_ms"]
            print(f"  Step latency: p50 {latency['p50']:.2f}ms, p95 {latency['p95']:.2f}ms, p99 {latency['p99']:.2f}ms")
        print(f"  {result['steps']} transitions in {result['measured_seconds']:.2f}s; "
              f"{result['completed_episodes']} terminal episodes, {result['resets']} resets "
              f"taking {result['reset_seconds']:.2f}s ({result['reset_fraction']:.1%} of measured time)")
        if result["mean_reset_seconds"] is not None:
            print(f"  Mean game reset: {result['mean_reset_seconds'] * 1000:.2f}ms including its RGB observation")
        print(f"  Cold start {result['startup_seconds']:.2f}s, warmup {result['warmup_seconds']:.2f}s (excluded)")
        print(f"  Uncompressed RGB: {result['rgb_mib_per_second']:.1f} MiB/s, "
              f"{result['raw_rgb_gb_per_hour']:.0f} GB/hour if every frame is stored")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
            print("  Report:", args.output)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
