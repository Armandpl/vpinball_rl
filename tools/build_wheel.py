# /// script
# requires-python = ">=3.10"
# dependencies = ["wheel>=0.45", "packaging>=24", "patchelf>=0.17",
#                 "olefile>=0.47", "extract-msg>=0.55", "pycryptodome>=3.20"]
# ///
"""Build an Ubuntu 24.04 x86-64 wheel: uv run tools/build_wheel.py --version 0.1.0."""
import argparse
import os
from pathlib import Path
import platform
import re
import runpy
import shutil
import subprocess
import tempfile

from packaging.version import Version
from wheel.wheelfile import WheelFile

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "third-party/runtime-libs/linux-x64"
# Supplied by Ubuntu, not the wheel. GPU drivers/Vulkan and Xvfb also remain external.
SYSTEM_LIBS = {"libc.so.6", "libm.so.6", "libmvec.so.1", "libpthread.so.0",
               "libdl.so.2", "librt.so.1", "libstdc++.so.6", "libgcc_s.so.1",
               "libudev.so.1", "libcap.so.2", "ld-linux-x86-64.so.2"}


def run(*args, timeout=600):
    subprocess.run(args, cwd=ROOT, check=True, timeout=timeout)


def bundle_native(destination):
    """Copy only the engine's dependency closure, using runtime SONAME filenames."""
    destination.mkdir()
    pending = [ROOT / "build/VPinballX_BGFX"]
    while pending:
        source = pending.pop()
        target = destination / source.name
        if target.exists():
            continue
        shutil.copy2(source, target)  # Dereference symlinks; wheels cannot preserve them.
        dynamic = subprocess.check_output(["readelf", "-d", str(target)], text=True, timeout=30)
        for name in re.findall(r"\(NEEDED\).*\[(.*?)\]", dynamic):
            if name in SYSTEM_LIBS:
                continue
            library = LIBS / name
            if not library.is_file():
                raise RuntimeError(f"Missing native dependency: {library}")
            pending.append(library)
        run("patchelf", "--set-rpath", "$ORIGIN", str(target))
        run("strip", "--strip-unneeded", str(target))
    # Copy tracked resources, not the build tree's potentially stale caches/plugins.
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "src/assets", "scripts"], cwd=ROOT, timeout=30).split(b"\0")
    for name in filter(None, tracked):
        source = Path(os.fsdecode(name))
        relative = source.relative_to("src") if source.parts[0] == "src" else source
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.1.0", type=Version)
    parser.add_argument("--big-brave", type=Path,
                        help="Bundle this locally supplied Big Brave v601 VPX (requires redistribution permission)")
    parser.add_argument("--jobs", type=int, default=min(12, os.cpu_count() or 1))
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("Build on Ubuntu 24.04 x86-64; this is not a cross-platform wheel")
    distro = platform.freedesktop_os_release()
    if (distro.get("ID"), distro.get("VERSION_ID")) != ("ubuntu", "24.04"):
        parser.error("Use Ubuntu 24.04 to keep the wheel's system ABI baseline consistent")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    # Upstream builds third-party dependencies; no root access or package installation here.
    required = ("SDL3", "SDL3_image", "SDL3_ttf", "freeimage", "hidapi-hidraw", "winevbs", "bgfx")
    if not all((LIBS / f"lib{name}.so").is_file() for name in required):
        run("bash", "platforms/linux-x64/external.sh", timeout=7200)
    run("cmake", "-S", ".", "-B", "build", "-DRENDERER=BGFX",
        "-DCMAKE_BUILD_TYPE=Release", "-DPOST_BUILD_COPY_EXT_LIBS=ON")
    run("cmake", "--build", "build", "--target", "vpinball", "-j", str(args.jobs), timeout=3600)
    runpy.run_path(str(ROOT / "vprl/build_table.py"), run_name="__main__")
    big_brave = None
    if args.big_brave is not None:
        builder = runpy.run_path(str(ROOT / "vprl/build_big_brave.py"))
        big_brave = builder["build"](args.big_brave.resolve())
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    tag = "py3-none-linux_x86_64"  # Deliberately not a manylinux portability claim.
    name = f"vprl-{args.version}"
    with tempfile.TemporaryDirectory(prefix="vprl-wheel-") as work:
        stage = Path(work)
        package = stage / "vprl"
        package.mkdir()
        for filename in ("__init__.py", "client.py", "camera.py", "tables.json"):
            shutil.copy2(ROOT / "vprl" / filename, package / filename)
        (package / "assets").mkdir()
        shutil.copy2(ROOT / "vprl/assets/rl_table.vpx", package / "assets/rl_table.vpx")
        if big_brave is not None:
            shutil.copy2(big_brave, package / "assets/big_brave.vpx")
        bundle_native(package / "native")
        metadata = stage / f"{name}.dist-info"
        metadata.mkdir()
        (metadata / "WHEEL").write_text(
            f"Wheel-Version: 1.0\nGenerator: vprl\nRoot-Is-Purelib: false\nTag: {tag}\n")
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: vprl\nVersion: {args.version}\n"
            "Summary: Synchronous headless Visual Pinball environment\n"
            "Requires-Python: >=3.10\nRequires-Dist: numpy>=1.26\n"
            "Provides-Extra: viewer\nRequires-Dist: raylib>=6.0.1.0; extra == 'viewer'\n"
            "Requires-External: Xvfb\nRequires-External: Vulkan\n\n"
            "Built for Ubuntu 24.04 x86-64. Requires Xvfb and a working Vulkan driver.\n")
        for source, filename in (("LICENSE", "LICENSE"), ("docs/license.txt", "THIRD_PARTY_LICENSES.txt"),
                                 ("third-party/README.md", "THIRD_PARTY.md"),
                                 ("platforms/config.sh", "DEPENDENCY_VERSIONS.sh")):
            shutil.copy2(ROOT / source, metadata / filename)
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=30).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True, timeout=30)
        (metadata / "BUILD.txt").write_text(
            f"Source revision: {revision}\nTracked changes: {bool(dirty)}\n"
            f"Build host: {distro['PRETTY_NAME']} / {platform.platform()}\n")
        wheel = output / f"{name}-{tag}.whl"
        with WheelFile(wheel, "w") as archive:
            archive.write_files(stage)
    print(f"\nBuilt {wheel} ({wheel.stat().st_size / 1024**2:.1f} MiB)")
    print(f"Install: uv pip install {wheel}")


if __name__ == "__main__":
    main()
