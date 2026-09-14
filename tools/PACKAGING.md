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
