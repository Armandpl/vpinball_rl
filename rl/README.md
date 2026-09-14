# RL pinball: one saved table

The table is **`rl/assets/rl_table.vpx`**, a small mod of VPX's bundled
`src/assets/strippedTable.vpx`. Its geometry and complete script are saved inside
the VPX. The client never patches a script or constructs geometry at runtime.

## Play

With native dependencies already built (see [upstream build instructions](../make/README.md)):

```bash
cmake -S . -B build -DRENDERER=BGFX -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 12

uv run examples/rl_play.py
uv run examples/rl_play.py --camera physical
# Server/container, automatic launch and no flipper policy:
uv run examples/rl_play.py --no-viewer --ticks 1000 --steps 300 --output /tmp/frame.png

# Ordinary VPX, with exactly the same saved table and rules:
./build/VPinballX_BGFX -Play rl/assets/rl_table.vpx
```

Python viewer controls: **A/left arrow/left shift**, **D/right arrow/right shift**,
**Space** to launch, **R** to reset, **Esc** to quit. Click the window for focus.
The table serves one ball at initialization. Space pulls the plunger for exactly
1000 simulated milliseconds, then releases automatically. Holding Space does not
retrigger. After a drain, R starts a fresh episode; Space alone does not reset.
In ordinary VPX, use its normal keys (typically Shift flippers, hold/release Enter
for the plunger); reload the table for another episode.

Interactive play follows wall-clock time: the viewer requests enough 1 ms ticks
per frame to account for capture/display delays (for example, alternating 16/17
ticks on a 60 Hz display). `--ticks` sets the target observation interval, not a
hard cap on simulated progress in this mode. Long stalls are capped at 250 ms
(or the requested interval, if larger). Reset discards startup-time debt. The
window title reports displayed FPS, simulated/wall-clock speed (`1.00x` is real
time), and average engine step/readback latency. `--fixed-step` restores exact
N-ticks-per-displayed-frame behavior for comparison, which can run slow if the
viewer cannot sustain that cadence. `--no-viewer` and the `Pinball.step()` API
remain fixed-tick and unpaced; training semantics are unchanged.

The raylib/pyray viewer displays RGB from the engine. `uv` installs its Python
dependencies automatically. It needs a desktop display; use `--no-viewer` in a
container without desktop forwarding. The engine uses its own private Xvfb;
install `xvfb` on whichever machine runs the script, not just inside Docker.

NVIDIA containers need `--gpus all` and
`NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display`. Vulkan on NVIDIA
is verified on an RTX 5090 in Ubuntu 24.04. Xvfb/OpenGL normally uses CPU llvmpipe;
`game.engine_info` reports the selected renderer and PCI vendor/device IDs.
NVIDIA vendor ID is `0x10de`. No host X socket is needed for headless runs.

## Table rules and minimal modifications

- **Five broad, rounded stand-up targets**, in a fan across the upper/middle
  playfield, intended to catch incidental launch/return paths as well as aimed
  shots. They use stock-height faces and shallow bases instead of the previous
  tall rectangular geometry, improving clearance beside the rightmost target.
- Exactly one associated insert is lit, initially target 1. Targets are numbered
  left to right, 1..5.
- **100 points for a lit hit**, then advance cyclically to the next target.
  **10 for an unlit hit**, without changing the active target. No other scoring.
- Per-target **100 ms simulated-time debounce** prevents one impact producing
  multiple awards. Light changes are driven by hits, not wall-clock timers.
- **One ball**; draining ends the episode. No automatic replacement, ball saver,
  missions, multiball, or bonus rules.
- Two solid, sloped return walls seal the side-outlane approaches and redirect
  the ball inward. The ordinary center drain remains. There is no teleporting
  or scripted side-drain rescue.
- Original geometry, flipper tuning, slingshots, sounds, animations, manual ball
  control code and **nudge handlers are preserved**. The RL harness exposes only
  left/right/start, so an agent cannot nudge.
- A uniform **dark-blue playfield** improves contrast with the silver ball,
  neutral targets and green indicators. Only its material color/image reference
  changes; material physics and other objects' colors are preserved.
- Original dimensions: **952 x 2162 VPU = 20.23 x 45.94 inches**.

The saved mod changes only the original GameData stream (script, part count and playfield color)
and integrity hash; all original object/asset streams remain byte-identical.
It adds 12 object streams: 5 targets, 5 lights, 2 returns. Script changes are the
one-ball drain behavior, a launch-start flag, and the added rules/RL methods.
`rl/assets/embedded_script.txt` is an exact readable copy for review, not a script
override. Do not rename it to `rl_table.vbs` beside the table.

### Offline authoring

The binary is checked in and ready to use. If changing the layout/rules:

```bash
uv run rl/build_table.py
```

This **offline** tool derives the mod from the bundled stripped table, using a
stock example-table target as an object template. Geometry is in
`rl/build_table.py`; appended rules are in `rl/five_targets_hooks.vbs`.
It regenerates both the VPX and script listing and recalculates VPX's legacy
MD2 integrity hash. Its hash implementation is checked against the unmodified
source table before writing. Authoring dependencies are not runtime dependencies.
No downloaded tables are used or redistributed.

## Python API

```python
# uv run --with numpy your_script.py
from rl import Action, Pinball

with Pinball(width=640, height=480, physics_ticks=16) as game:
    obs = game.step(physics_ticks=0)
    obs = game.step(Action(start=True), physics_ticks=1000)
    while not obs.game_over:
        obs = game.step(Action(left=True))  # Example calls, not a useful policy.
        rgb = obs.frame                    # Owned uint8 H x W x 3, RGB.
        score = obs.score
    obs = game.reset()
```

- Physics uses the existing **1000 Hz / 1 ms** integrator and collision substeps.
  `step` holds the action for exactly N ticks, renders one observation, then waits.
  The engine checks its actual physics clock against cumulative requested ticks.
- `physics_ticks=16` means 62.5 observations per simulated second; 20 means 50;
  100 means 10. The range is 0..10000, overridable per call. Zero ticks applies
  input and renders, but does not advance physics.
- Observations: `ticks`, `score`, `game_over`, `started`, `balls_left`,
  `launch_pending`, `active_target`, `frame`. `active_target` is privileged state
  (1..5); an outer Gymnasium wrapper can omit it for pixel-only training.
- `reset()` starts a **new game in the same engine process**: removes any active
  ball (also works mid-episode), clears score/game-over/target/cooldown/button and
  launch state, releases the flippers/plunger, resets table visual/sound state,
  and serves exactly one fresh ball. It returns RGB at episode tick zero.
  The engine's physics/timer clock stays monotonic; only the reported episode
  tick origin changes. Animations/physics are not restored to a precise snapshot.
  There is **no process-restart reset or fallback**, and resetting a closed client
  raises an error. Renderer, GPU resources, sockets and Xvfb stay alive until close.
  The table copy, preferences and caches remain private; the source VPX is copied
  byte-for-byte and never overwritten.
- `table=` can select another already-authored VPX with embedded `RLApplyAction`,
  `RLTick`, `RLObserve`, and `RLReset` methods (transport protocol v2). No ZIP loading, runtime adapters, or table
  generation is performed. The only supported/default game is the saved mod.
- Normal VPX play is unchanged unless launched through the private RL transport.

## Physical camera

`--camera physical` uses `fx=fy=1141.5`, `cx=672`, `cy=380` at **1344 x 760**,
**16 inches perpendicular above the flipper-end edge**, centered left/right,
looking toward the bumpers at **45 degrees down from the plane**, with **90 degrees
clockwise physical roll** (viewed from behind the camera toward the scene).
There is no table resizing or automatic camera fitting.

Raw observations and saved `--output` images remain **1344 x 760 sensor images**
with the original intrinsics. The viewer rotates them clockwise into upright
**760 x 1344 portrait**. Use `--view-rotation 0` to inspect raw orientation.

```bash
uv run examples/rl_play.py --camera physical --camera-y-inches -2 --camera-tilt 50
```

Positive X moves rightward; positive Y moves toward the player from the anchor;
negative Y moves into the table. `--camera-anchor center` instead positions the
camera relative to the geometric center. `--camera-roll 0` disables physical
roll. Arbitrary rolls are supported; automatic upright display handles quarter
turns only. Changing render resolution scales K, not the scene; changing aspect
ratio corresponds to nonuniform resizing.

```python
from rl import Camera, Pinball
with Pinball(camera=Camera(height_mm=406.4, tilt_degrees=45, roll_degrees=90,
                         anchor="flipper_end"), width=1344, height=760) as game:
    image = game.step(physics_ticks=0).frame
```

Units use VPX's **50 VPU = 1.0625 inches** convention; native playfield Z=0.
Near/far defaults: 1 mm / 10 m. Intrinsics are pinhole only: lens distortion and
camera yaw are not implemented. The table's normal 2D score overlay is retained.

## Rollout throughput benchmark

```bash
# Default sweep: full, half and quarter camera resolution; one environment.
uv run examples/rl_benchmark.py --seconds 30 --output /tmp/vpx-benchmark.json
# Compare observation rates at one resolution:
uv run examples/rl_benchmark.py --resolutions 672x380 --ticks 8 16 32 --seconds 60
```

Each measured step is a real `Pinball.step()` with fixed physics ticks, rendering,
readback and an owned RGB array delivered to Python. No viewer or real-time pacing
is involved. Random flipper actions change in 100 ms simulated-time blocks, with
periodic launch pulses. Terminal states trigger in-process game resets; the
benchmark never pads its count by stepping an already-ended episode.

Two rates are reported:
- **Step calls/s:** excludes resets and policy/bookkeeping time, includes everything
  inside `step()` (physics + render + readback + IPC + array allocation).
- **Rollout steps/s:** includes policy/bookkeeping and resets during measurement.
  This is the better estimate of useful transitions collected by one environment.

Cold startup, warmup and final shutdown are excluded and reported separately.
A reset crossing the requested duration finishes and counts toward the actual
elapsed time. Reset observations are not counted as action transitions. Reports
include p50/p95/p99 step latency, reset costs, simulated-time speedup, transitions
per hour, uncompressed RGB volume, GPU/driver information and engine/table hashes.
The seed controls actions only; VPX physics is not seeded by this tool.

Initial single-RTX-5090/Vulkan measurements in this container, 30 seconds per
configuration, physical camera and **16 physics ticks per observation**:

| Sensor resolution | Step calls/s | Rollout steps/s (resets included) | Transitions/hour | Time spent resetting |
|---|---:|---:|---:|---:|
| 1344 x 760 | 286 | 285 | 1,027,000 | <0.2% |
| 672 x 380 | 680 | 678 | 2,440,000 | <0.2% |
| 336 x 190 | 850 | 847 | 3,051,000 | <0.2% |

These are short baseline samples, not a guaranteed training rate: episode length,
actions, other GPU workloads and agent inference/training all affect throughput.
Game resets now take roughly **1–4 milliseconds**, including the returned RGB
observation. The former process-restart implementation took about 2.5 seconds
and achieved 190 / 270 / 293 rollout steps/s; that reset path has been removed.
Cold startup still costs about 2.3 seconds, paid once per client.
Storing every RGB frame uncompressed would use approximately 3.1 TB/hour at full
resolution, or 584 GB/hour at quarter resolution in this run; this is a data-volume
estimate, not measured disk throughput. Multiple parallel environments have not
been benchmarked yet.

## Tests

```bash
uv run --with numpy --with extract-msg --with pycryptodome \
  python -m unittest rl.test_table rl.test_client rl.test_camera rl.test_viewer rl.test_benchmark -v
```

Tests verify saved-file integrity, minimal stream changes, preservation of nudge
code, byte-identical runtime copies, real target collisions and lit/unlit scores,
all five active-target transitions, clearance past the rightmost target,
inward deflection from both side approaches,
launch timing, complete episodes, terminal detection, repeated mid-game resets,
process/socket identity, single-ball respawn, monotonic native time and camera math.
Physics fixtures author separate temporary diagnostic VPX files offline; no debug
or teleport actions are exposed by the production table/client.

## Limitations / next steps

- No deterministic seed API or cross-run bitwise reproducibility guarantee yet.
  Temporal dithering can vary pixels even when physics is frozen.
- Regular timers follow physics; existing per-render (`-1`) callbacks still run
  once per observation. Thus zero-tick calls are not entirely script-side-effect-free.
- One client per thread; use separate instances for independent engine processes.
- Raw RGB uses a private inherited Unix socketpair and BGFX framebuffer readback,
  including a pipeline flush. No screen scraping, PNG encoding or public listener
  is involved in stepping. Engine timeouts include log tails.
- No Gymnasium wrapper, agent reward function, PinMAME synchronization, parallel
  environment benchmark or distributable native/Python packaging yet; those remain
  separate work.
