// Local BGFX Vulkan selector. No CUDA, Mesa layer, or Vulkan tools dependency.
#pragma once
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace vpx_gpu
{
using UUID = std::array<unsigned char, 16>;

inline int hex(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

inline bool parse(const char* text, UUID& uuid)
{
    if (!text) return false;
    if (std::strncmp(text, "GPU-", 4) == 0 || std::strncmp(text, "gpu-", 4) == 0) text += 4;
    if (std::strlen(text) != 36) return false;
    unsigned pos = 0;
    for (unsigned i = 0; i < uuid.size(); ++i)
    {
        if (i == 4 || i == 6 || i == 8 || i == 10)
            if (text[pos++] != '-') return false;
        const int hi = hex(text[pos++]);
        const int lo = hex(text[pos++]);
        if (hi < 0 || lo < 0) return false;
        uuid[i] = static_cast<unsigned char>((hi << 4) | lo);
    }
    return true;
}

inline void format(const UUID& uuid, char (&text)[37])
{
    unsigned pos = 0;
    const char* digits = "0123456789abcdef";
    for (unsigned i = 0; i < uuid.size(); ++i)
    {
        if (i == 4 || i == 6 || i == 8 || i == 10) text[pos++] = '-';
        text[pos++] = digits[uuid[i] >> 4];
        text[pos++] = digits[uuid[i] & 15];
    }
    text[pos] = '\0';
}

[[noreturn]] inline void fail(const char* reason)
{
    std::fprintf(stderr, "VPX_GPU_UUID: %s\n", reason);
    std::fflush(stderr);
    // BGFX can retry initialization with a different renderer after an init error.
    // An explicit GPU assignment must never silently fall back.
    std::exit(EXIT_FAILURE);
}

inline unsigned select(const char* requested, const std::vector<UUID>& devices)
{
    UUID wanted{};
    if (!parse(requested, wanted) || wanted == UUID{})
        fail("expected a nonzero canonical GPU UUID (optional GPU- prefix)");
    for (unsigned i = 0; i < devices.size(); ++i)
        if (devices[i] == wanted) return i;
    fail("requested GPU is not exposed by Vulkan");
}
}
