# Build and install vprl

Build on **Ubuntu 24.04 x86-64**, with the [upstream build prerequisites](../make/README.md):

```sh
uv run tools/build_wheel.py --version 0.1.0
```

This builds missing third-party libraries, builds the BGFX engine, generates the
table, and writes `dist/vprl-0.1.0-py3-none-linux_x86_64.whl`. Subsequent builds
reuse the native build directory. Plugins and table-authoring Python dependencies
are not included. The wheel includes the engine's shared libraries, assets,
scripts, table, and license notices. Publish it at any downloadable URL.

On the training machine (also Ubuntu 24.04 x86-64):

```sh
sudo apt install xvfb libvulkan1 libudev1 libcap2 libstdc++6 \
  libx11-6 libxext6 libxcursor1 libxi6 libxrandr2 libxfixes3 libxss1 libxkbcommon0
# Install the appropriate Vulkan GPU driver separately.
uv venv
uv pip install https://your-host/vprl-0.1.0-py3-none-linux_x86_64.whl
```

For an existing uv project, use `uv add <wheel URL>` instead. No compiler, source
checkout, or engine path is needed on the training machine:

```python
from vprl import Action, Camera, Pinball

with Pinball(width=640, height=480) as game:
    obs = game.reset()
    while True:
        obs = game.step(Action(left=True))
        if obs.game_over:
            obs = game.reset()
```

## Big Brave (optional bundle)

Instrument the locally supplied **Big Brave (Maresa 1974) v601.vpx** by JPSalas:

```sh
uv run vprl/build_big_brave.py "Big Brave (Maresa 1974) v601.vpx"
uv run examples/rl_play.py --table big_brave
uv run tools/build_wheel.py --version 0.1.0 --big-brave "Big Brave (Maresa 1974) v601.vpx"
```

The last command bundles both tables. Without `--big-brave`, the wheel contains
only the simple table (no download is performed). Select with
`Pinball(table="big_brave")` or `Pinball(table="rl_table")` (default).
The selected table's metadata is available as `game.table_info`.

Big Brave reports the original single-player score and game-over flag directly
from VBScript, including end-of-ball bonus scoring. Every ball is automatically
plunged. Observations contain only `frame`, `ticks`, `score`, and `game_over`.
Call `reset()` before the first action.
Both tables use the same two-engine pool. Construction prepares two fresh
engines; `reset()` swaps to the ready engine and replaces the retired engine in
a background thread. This clears all pending state, even on mid-game resets.
The ready engine stays at tick zero until stepped. Expect roughly twice the
RAM/VRAM and a longer initial startup. If episodes finish before replacement
startup completes, reset waits for the spare; background startup can also
compete with stepping for GPU resources. `close()` waits for pending startup
and cleans up both engines.

Credit: **JPSalas**, Big Brave 6.0.1,
[original download and discussion](https://www.vpforums.org/index.php?app=downloads&showfile=15045&st=0#comment_29527).

## Selecting a Vulkan GPU

Set `VPX_GPU_UUID` before constructing `Pinball`, using the assigned CUDA device's
UUID (canonical UUID, optionally prefixed with `GPU-`). For example, in a worker
whose `CUDA_VISIBLE_DEVICES` already isolates its training GPU:

```python
import os
import torch
os.environ["VPX_GPU_UUID"] = str(torch.cuda.get_device_properties(0).uuid)
```

The local BGFX patch enumerates all Vulkan devices (upstream capped enumeration
at four), matches `VkPhysicalDeviceIDProperties.deviceUUID`, and exits on malformed
or unavailable UUIDs instead of falling back. The engine reports the selected UUID
in `game.engine_info["gpu_uuid"]`; the client verifies it against the request,
including for spare engines. No Mesa selection layer or `vulkaninfo` is needed.
Vulkan-capable NVIDIA drivers are still required; MIG is not supported.

RL now renders **offscreen by default**: BGFX initializes without a window
swapchain, renders the final image to a BGRA8 texture, and blits/readbacks that
texture to CPU before replying. This avoids requiring the assigned GPU to present
to Xvfb (which may only support another GPU). Xvfb remains for SDL/window setup,
but Vulkan never presents to it. GPU UUID checks and no-fallback behavior remain
enforced. Set `VPX_RL_OFFSCREEN=0` only to compare with the old swapchain path.

Local native regression (run from this repository with numpy installed):

```sh
VPRL_GPU_TESTS=1 VPX_GPU_UUID=<gpu-uuid> python -m unittest discover -s tests -p test_rl_offscreen.py
```

It compares initial offscreen/windowed pixels exactly and exercises stepping and
pooled resets. The windowed comparison may fail on secondary cluster GPUs—that is
the presentation limitation the offscreen path avoids.

`tools/build_wheel.py` automatically rebuilds BGFX when the selector patch changes,
even if third-party libraries already exist. To build only the patched library:

```sh
bash tools/build_bgfx.sh 8
```

The patch and helper are `tools/bgfx_gpu_uuid.patch` and `tools/bgfx_gpu_uuid.h`,
applied to the BGFX revision pinned in `platforms/config.sh`. Publish a **new wheel
version** and update the training project's wheel URL/lockfile before enabling
UUID selection there. An older engine/wheel is rejected rather than silently
ignoring the assignment. Test on a multi-GPU node, including local GPU 7, before
launching the full sweep.

## Camera and runtime

`Camera(INTRINSICS, EXTRINSICS)` works as in `examples/rl_play.py`, including
automatic intrinsics scaling. For a desktop viewer, also install `raylib` (or the
wheel's `viewer` extra). Training does not depend on raylib or a desktop display.
NVIDIA containers need GPU passthrough and graphics/display driver capabilities.

This is a Linux wheel, **not manylinux**: it relies on the build distribution's
system ABI and does not bundle glibc, GPU drivers, or Xvfb. Other distributions
and architectures are not currently supported. A successful local smoke test
does not establish portability to older distributions.

When distributing the binary, also make the corresponding engine and dependency
sources/build instructions available as required by their licenses. Included
notices are not a substitute for source-distribution obligations. Build from a
committed revision for release; `BUILD.txt` records the source revision.
