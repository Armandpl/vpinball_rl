// license:GPLv3+
#pragma once

// Opt-in Linux/BGFX transport. The launcher passes a connected socket, never a
// publicly listening port. One command and one RGB observation are in flight.
#if defined(__linux__) && defined(ENABLE_BGFX)
#include <sys/socket.h>
#include <unistd.h>
#include <atomic>
#include <array>
#include <cmath>
#include <sstream>
#include <stdexcept>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

class RLBridge
{
public:
   static RLBridge& Get() { static RLBridge bridge; return bridge; }
   bool Enabled() const { return m_fd >= 0; }
   bool Receive(std::string& line)
   {
      line.clear();
      char ch;
      while (line.size() < 256)
      {
         const auto n = recv(m_fd, &ch, 1, 0);
         if (n < 0 && errno == EINTR) continue;
         if (n != 1) return false;
         if (ch == '\n') return true;
         line += ch;
      }
      return false;
   }
   bool Send(const void* data, size_t size)
   {
      auto p = static_cast<const char*>(data);
      while (size)
      {
         const auto n = send(m_fd, p, size, MSG_NOSIGNAL);
         if (n < 0 && errno == EINTR) continue;
         if (n <= 0) return false;
         p += n; size -= n;
      }
      return true;
   }
   bool Send(const std::string& text) { return Send(text.data(), text.size()); }

   bool hasCamera = false;
   bool cameraAtFlipperEnd = false;
   std::array<float, 32> cameraMatrices {}; // Row-vector view and projection, relative to table anchor.

   std::atomic<bool> captureRequested { false };
   std::atomic<bool> captureReady { false };
   // Written by render callback, published through captureReady.
   std::vector<unsigned char> rgb;
   unsigned width = 0, height = 0;
   bool captureOK = false;

   void Capture(unsigned w, unsigned h, unsigned pitch, const void* data, unsigned size, bool bgra, bool supported, bool flip)
   {
      captureOK = supported && w && h && pitch >= w * 4 && uint64_t(pitch) * h <= size;
      if (captureOK)
      {
         width = w; height = h;
         rgb.resize(size_t(w) * h * 3);
         for (unsigned y = 0; y < h; ++y)
         {
            const auto src = static_cast<const unsigned char*>(data) + size_t(flip ? h - 1 - y : y) * pitch;
            auto dst = rgb.data() + size_t(y) * w * 3;
            for (unsigned x = 0; x < w; ++x)
            {
               dst[3*x] = src[4*x + (bgra ? 2 : 0)];
               dst[3*x+1] = src[4*x+1];
               dst[3*x+2] = src[4*x + (bgra ? 0 : 2)];
            }
         }
      }
      captureReady.store(true);
   }
private:
   RLBridge()
   {
      const char* value = std::getenv("VPX_RL_FD");
      if (value)
      {
         char* end;
         const long fd = std::strtol(value, &end, 10);
         if (*value && !*end && fd >= 3 && fd <= 0x7fffffff) m_fd = int(fd);
      }
      if (const char* camera = std::getenv("VPX_RL_CAMERA"); Enabled() && camera)
      {
         std::istringstream input(camera);
         for (float& value : cameraMatrices)
            if (!(input >> value) || !std::isfinite(value))
               throw std::runtime_error("VPX_RL_CAMERA requires 32 finite matrix values");
         std::string extra;
         if (input >> extra) throw std::runtime_error("Unexpected VPX_RL_CAMERA data");
         const char* anchor = std::getenv("VPX_RL_CAMERA_ANCHOR");
         if (anchor && std::strcmp(anchor, "center") && std::strcmp(anchor, "flipper_end"))
            throw std::runtime_error("Unknown VPX_RL_CAMERA_ANCHOR");
         cameraAtFlipperEnd = anchor && std::strcmp(anchor, "flipper_end") == 0;
         hasCamera = true;
      }
   }
   int m_fd = -1;
};
#endif
