import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

import numpy as np

PACKAGE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Action:
    left: bool = False
    right: bool = False


@dataclass(frozen=True)
class Observation:
    frame: np.ndarray  # uint8 RGB, H x W x 3; independently owned
    ticks: int
    score: int
    game_over: bool


class _Engine:
    """Private single-process transport; owned by one thread at a time."""

    def __init__(self, *, width=640, height=480, physics_ticks=16, camera=None,
                 engine=None, timeout=60.0, table="rl_table"):
        tables = json.loads((PACKAGE / "tables.json").read_text())
        if table not in tables:
            raise ValueError(f"Unknown table {table!r}; choose from {', '.join(tables)}")
        self.table_info = tables[table]
        self.table = table
        self._table_path = PACKAGE / "assets" / self.table_info["asset"]
        if engine is None:
            native = PACKAGE / "native/VPinballX_BGFX"
            engine = native if native.is_file() else PACKAGE.parent / "build/VPinballX_BGFX"
        self.engine = Path(engine).resolve()
        for path in (self.engine, self._table_path):
            if not path.is_file():
                raise FileNotFoundError(path)
        if not (type(width) is int and type(height) is int and 64 <= width <= 4096 and 64 <= height <= 4096):
            raise ValueError("width and height must be 64..4096")
        self._validate_ticks(physics_ticks)
        if not 0 < timeout < float("inf"):
            raise ValueError("timeout must be positive")
        self._camera = camera.serialize(width, height) if camera is not None else None
        self._camera_anchor = camera.anchor if camera is not None else None
        self.width, self.height = width, height
        self.physics_ticks, self.timeout = physics_ticks, timeout
        self._proc = self._xvfb = self._sock = self._stream = self._log = self._tmp = None
        try:
            self._launch()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _validate_ticks(ticks):
        if type(ticks) is not int or not 0 <= ticks <= 10000:
            raise ValueError("physics_ticks must be an integer in 0..10000")

    def _launch(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vpx-rl-")
        work = Path(self._tmp.name)
        self.log_path = work / "engine.log"
        self._log = self.log_path.open("wb")
        env = os.environ.copy()
        # Only BGFX in this engine process may report the selected device.
        env.pop("VPX_SELECTED_GPU_UUID", None)
        for key in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            path = work / key.lower()
            path.mkdir(mode=0o700)
            env[key] = str(path)
        env["SDL_AUDIODRIVER"] = "dummy"
        env.pop("VPX_RL_CAMERA", None)
        env.pop("VPX_RL_CAMERA_ANCHOR", None)
        if self._camera is not None:
            env["VPX_RL_CAMERA"] = self._camera
            env["VPX_RL_CAMERA_ANCHOR"] = self._camera_anchor
        read_fd, write_fd = os.pipe()
        try:
            self._xvfb = subprocess.Popen(
                ["Xvfb", "-noreset", "-displayfd", str(write_fd), "-screen", "0",
                 f"{self.width}x{self.height}x24", "-nolisten", "tcp"],
                pass_fds=(write_fd,), stdout=self._log, stderr=self._log)
            os.close(write_fd)
            write_fd = None
            # Xvfb may write the digits and newline separately; wait for both.
            deadline = time.monotonic() + self.timeout
            line = b""
            while b"\n" not in line and len(line) < 64:
                remaining = max(0, deadline - time.monotonic())
                if not select.select([read_fd], [], [], remaining)[0]:
                    raise TimeoutError("Xvfb startup timed out")
                chunk = os.read(read_fd, 64)
                if not chunk:
                    break
                line += chunk
            display = line.decode().strip()
            if not display.isdigit():
                raise RuntimeError("Xvfb failed to allocate a display")
            env["DISPLAY"] = ":" + display
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
        # Isolate table-adjacent settings and caches between instances.
        table = work / "table.vpx"
        shutil.copyfile(self._table_path, table)
        ini = work / "VPinballX.ini"
        ini.write_text(f"""[Player]
GfxBackend = Vulkan
PlayfieldFullScreen = 0
PlayfieldWidth = {self.width}
PlayfieldHeight = {self.height}
SyncMode = 0
MaxFramerate = 10000
MusicVolume = 0
SoundVolume = 0
ForceMotionBlurOff = 1
""")
        parent, child = socket.socketpair()
        self._sock = parent
        parent.settimeout(self.timeout)
        env["VPX_RL_FD"] = str(child.fileno())
        try:
            self._proc = subprocess.Popen(
                [str(self.engine), "-Ini", str(ini), "-Play", str(table)],
                cwd=self.engine.parent, env=env, pass_fds=(child.fileno(),),
                stdout=self._log, stderr=self._log)
        finally:
            child.close()
        self._stream = parent.makefile("rb")
        hello = self._header()
        self.engine_info = hello
        if hello.get("protocol") != 3 or hello.get("physics_tick_us") != 1000:
            raise RuntimeError(f"Unsupported engine protocol: {hello}")
        requested_gpu = env.get("VPX_GPU_UUID")
        if requested_gpu is not None:
            expected = requested_gpu.lower().removeprefix("gpu-")
            if hello.get("renderer") != "Vulkan" or hello.get("gpu_uuid") != expected:
                raise RuntimeError(f"Engine GPU mismatch: requested {expected}, got {hello}. "
                                   "Rebuild the engine and BGFX with UUID selection support.")

    def _header(self):
        try:
            line = self._stream.readline(65537)
            if not line or len(line) > 65536:
                raise RuntimeError("Engine disconnected or sent an invalid header")
            header = json.loads(line)
            if "error" in header:
                raise RuntimeError(header["error"])
            return header
        except (OSError, ValueError, RuntimeError) as exc:
            with self.log_path.open("rb") as log:
                log.seek(max(0, self.log_path.stat().st_size - 8000))
                tail = log.read().decode(errors="replace")
            raise RuntimeError(f"{exc}\nEngine log:\n{tail}") from exc

    def step(self, action=Action(), *, physics_ticks=None):
        if self._sock is None:
            raise RuntimeError("Client is closed")
        count = self.physics_ticks if physics_ticks is None else physics_ticks
        self._validate_ticks(count)
        bits = (action.left, action.right)
        if any(type(bit) is not bool for bit in bits):
            raise ValueError("Action fields must be bools")
        self._sock.sendall(f"step {int(bits[0])} {int(bits[1])} {count}\n".encode())
        return self._observation()

    def _observation(self):
        header = self._header()
        w, h, size = header["width"], header["height"], header["bytes"]
        if not (0 < w <= 4096 and 0 < h <= 4096 and size == w*h*3):
            raise RuntimeError(f"Invalid frame dimensions: {header}")
        data = self._stream.read(size)
        if len(data) != size:
            raise RuntimeError("Engine disconnected during frame transfer")
        frame = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3).copy()
        return Observation(frame=frame, ticks=header["ticks"], **header["state"])

    def reset(self):
        """Initialize a freshly launched engine, never reuse episode state."""
        if self._sock is None:
            raise RuntimeError("Client is closed")
        self._sock.sendall(b"reset\n")
        return self._observation()

    def close(self):
        if self._sock is not None:
            try:
                self._sock.settimeout(0.2)
                self._sock.sendall(b"close\n")
            except OSError:
                pass
        for proc in (self._proc, self._xvfb):
            if proc is not None:
                try:
                    if proc is self._xvfb:
                        proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        for resource in (self._stream, self._sock, self._log):
            if resource is not None:
                resource.close()
        if self._tmp is not None:
            self._tmp.cleanup()
        self._proc = self._xvfb = self._sock = self._stream = self._log = self._tmp = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Pinball:
    """Two-engine pool, using fresh processes for every table's episodes.

    Construction warms both engines. reset swaps to the prepared engine and
    rebuilds the retired one asynchronously. Short episodes may exhaust the
    spare and make reset wait. Instances must not be shared between threads.
    """

    def __init__(self, *, width=640, height=480, physics_ticks=16, camera=None,
                 engine=None, timeout=60.0, table="rl_table"):
        self._options = dict(width=width, height=height, physics_ticks=physics_ticks,
                             camera=camera, engine=engine, timeout=timeout, table=table)
        self.physics_ticks = physics_ticks
        self._active = None
        self._spare = None
        self._initial = None
        self._closed = False
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vprl-spare")
        try:
            self._active, self._initial = self._prepare()
            self._spare = self._worker.submit(self._prepare)
            # Pay the two-engine warmup once, not on the first episode boundary.
            self._spare.result()
            for name in ("width", "height", "timeout", "table", "table_info", "engine"):
                setattr(self, name, getattr(self._active, name))
        except BaseException:
            self.close()
            raise

    def _prepare(self, retired=None):
        if retired is not None:
            retired.close()
        engine = _Engine(**self._options)
        try:
            return engine, engine.reset()
        except BaseException:
            engine.close()
            raise

    @property
    def engine_info(self):
        return self._active.engine_info

    @property
    def log_path(self):
        return self._active.log_path

    def step(self, action=Action(), *, physics_ticks=None):
        if self._closed:
            raise RuntimeError("Client is closed")
        count = self.physics_ticks if physics_ticks is None else physics_ticks
        obs = self._active.step(action, physics_ticks=count)
        self._initial = None
        return obs

    def reset(self):
        """Return a fresh tick-zero episode, waiting only if the spare is unready."""
        if self._closed:
            raise RuntimeError("Client is closed")
        if self._initial is not None:
            obs, self._initial = self._initial, None
            return obs
        # Leave the active engine owned here until preparation succeeds.
        ready, obs = self._spare.result()
        retired, self._active = self._active, ready
        self._spare = self._worker.submit(self._prepare, retired)
        return obs

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._active is not None:
                self._active.close()
        finally:
            # Never abandon a startup thread: it may still own a live process.
            try:
                if self._spare is not None:
                    try:
                        spare, _ = self._spare.result()
                    except BaseException:
                        pass  # Startup errors surface in construction/reset.
                    else:
                        spare.close()
            finally:
                self._worker.shutdown(wait=True)
                self._active = self._spare = self._initial = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
