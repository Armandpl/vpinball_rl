#!/bin/bash
# Rebuild only BGFX, including our UUID selector; no full dependency rebuild.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BUILD_TYPE=${BUILD_TYPE:-Release}
source "$ROOT/platforms/config.sh"
PATCH_HASH=$(sha256sum "$ROOT/tools/bgfx_gpu_uuid.patch" "$ROOT/tools/bgfx_gpu_uuid.h" | sha256sum | cut -d' ' -f1)
EXPECTED="${BGFX_CMAKE_VERSION}-${BGFX_PATCH_SHA}-${PATCH_HASH}"
WORK="$ROOT/external/linux-x64/$BUILD_TYPE/bgfx"
mkdir -p "$WORK"
cd "$WORK"
if [[ ! -f cache.txt || "$(<cache.txt)" != "$EXPECTED" ]]; then
  curl --fail --location --max-time 180 "https://github.com/bkaradzic/bgfx.cmake/releases/download/v${BGFX_CMAKE_VERSION}/bgfx.cmake.v${BGFX_CMAKE_VERSION}.tar.gz" -o cmake.tar.gz
  curl --fail --location --max-time 180 "https://github.com/vbousquet/bgfx/archive/${BGFX_PATCH_SHA}.tar.gz" -o bgfx.tar.gz
  rm -rf bgfx.cmake "bgfx-${BGFX_PATCH_SHA}"
  tar xzf cmake.tar.gz
  tar xzf bgfx.tar.gz
  rm -rf bgfx.cmake/bgfx
  mv "bgfx-${BGFX_PATCH_SHA}" bgfx.cmake/bgfx
  patch -d bgfx.cmake/bgfx -p1 < "$ROOT/tools/bgfx_gpu_uuid.patch"
  cp "$ROOT/tools/bgfx_gpu_uuid.h" bgfx.cmake/bgfx/src/
  cmake -S bgfx.cmake -B bgfx.cmake/build \
    -DBGFX_LIBRARY_TYPE=SHARED -DBGFX_BUILD_TOOLS=OFF -DBGFX_BUILD_EXAMPLES=OFF \
    -DBGFX_CONFIG_MULTITHREADED=ON -DBGFX_CONFIG_MAX_FRAME_BUFFERS=256 \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE"
  cmake --build bgfx.cmake/build --parallel "${1:-8}"
  echo "$EXPECTED" > cache.txt
fi
cp -a bgfx.cmake/build/cmake/bgfx/libbgfx.so "$ROOT/third-party/runtime-libs/linux-x64/"
for library in bgfx bimg bx; do
  cp -r "bgfx.cmake/$library/include/$library" "$ROOT/third-party/include/"
done
