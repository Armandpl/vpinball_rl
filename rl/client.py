from __future__ import annotations

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

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Action:
    left: bool = False
    right: bool = False
    start: bool = False


@dataclass(frozen=True)
class Observation:
    frame: np.ndarray  # uint8 RGB, H x W x 3; independently owned
    ticks: int
    score: int
    game_over: bool
    started: bool
    balls_left: int
    launch_pending: bool
    active_target: int  # Saved table: 1..5, left to right.


class Pinball:
    """One engine process. step holds the action for physics_ticks fixed 1ms ticks.

    Start is edge-triggered and launches after a fixed 1000ms simulated pull.
    reset starts a new game in the same process; it is not a full physics snapshot.
    A private Xvfb is used by default; Python alone displays returned frames.
    Instances must not be shared between threads.
    """

    def __init__(self, *, engine=ROOT / "build/VPinballX_BGFX",
                 table=ROOT / "rl/assets/rl_table.vpx",
                 width=640, height=480,
                 physics_ticks=16, backend="Vulkan", headless=True, timeout=60.0,
                 camera=None):
        self.engine, self.table = Path(engine).resolve(), Path(table).resolve()
        for path in (self.engine, self.table):
            if not path.is_file():
                raise FileNotFoundError(path)
        if not (type(width) is int and type(height) is int and 64 <= width <= 4096 and 64 <= height <= 4096):
            raise ValueError("width and height must be 64..4096")
        self._validate_ticks(physics_ticks)
        if backend not in ("Vulkan", "OpenGL"):
            raise ValueError("backend must be Vulkan or OpenGL")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.camera = camera
        if camera is not None:
            camera.matrices(width, height)  # Validate before starting any processes.
        self.width, self.height = width, height
        self.physics_ticks, self.backend = physics_ticks, backend
        self.headless, self.timeout = headless, timeout
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
        for key in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
            path = work / key.lower()
            path.mkdir(mode=0o700)
            env[key] = str(path)
        env["SDL_AUDIODRIVER"] = "dummy"
        env.pop("VPX_RL_CAMERA", None)
        env.pop("VPX_RL_CAMERA_ANCHOR", None)
        if self.camera is not None:
            env["VPX_RL_CAMERA"] = self.camera.serialize(self.width, self.height)
            env["VPX_RL_CAMERA_ANCHOR"] = self.camera.anchor
        if self.headless:
            read_fd, write_fd = os.pipe()
            try:
                self._xvfb = subprocess.Popen(
                    ["Xvfb", "-noreset", "-displayfd", str(write_fd), "-screen", "0",
                     f"{self.width}x{self.height}x24", "-nolisten", "tcp"],
                    pass_fds=(write_fd,), stdout=self._log, stderr=self._log)
                os.close(write_fd)
                write_fd = None
                # Xvfb can write the digits and newline separately. Keep the pipe
                # open until the entire line arrives, or its final write can fail.
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
        # Byte-for-byte copy isolates settings/caches. No geometry or script patching:
        # the checked-in VPX already contains our layout and complete rules.
        table = work / "table.vpx"
        shutil.copyfile(self.table, table)
        ini = work / "VPinballX.ini"
        ini.write_text(f"""[Player]
GfxBackend = {self.backend}
PlayfieldFullScreen = 0
PlayfieldWidth = {self.width}
PlayfieldHeight = {self.height}
PlayfieldWndX = 0
PlayfieldWndY = 0
SyncMode = 0
MaxFramerate = 10000
MusicVolume = 0
SoundVolume = 0
ForceMotionBlurOff = 1
[Standalone]
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
        if hello.get("protocol") != 2 or hello.get("physics_tick_us") != 1000:
            raise RuntimeError(f"Unsupported engine protocol: {hello}")

    def _diagnostic(self):
        return self.log_path.read_text(errors="replace")[-8000:]

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
            raise RuntimeError(f"{exc}\nEngine log:\n{self._diagnostic()}") from exc

    def step(self, action=Action(), *, physics_ticks=None):
        if self._sock is None:
            raise RuntimeError("Client is closed")
        count = self.physics_ticks if physics_ticks is None else physics_ticks
        self._validate_ticks(count)
        bits = (action.left, action.right, action.start)
        if any(type(bit) is not bool for bit in bits):
            raise ValueError("Action fields must be bools")
        self._sock.sendall(f"step {int(bits[0])} {int(bits[1])} {int(bits[2])} {count}\n".encode())
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
        """Reset game state and serve a fresh ball, retaining engine and renderer.

        Works mid-episode too. Returns a frame at episode tick zero; native timer
        time remains monotonic. A closed client cannot be reset/restarted.
        """
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
