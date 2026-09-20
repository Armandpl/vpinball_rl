// license:GPLv3+
#include "core/stdafx.h"
#include "core/player.h"
#include "core/RLBridge.h"
#include "renderer/Renderer.h"

#if defined(__linux__) && defined(ENABLE_BGFX)
void Player::RLGameLoop()
{
   auto& bridge = RLBridge::Get();
   auto rd = m_renderer->m_renderDevice;
   uint64_t ticks = 0;
   uint64_t episodeOrigin = 0;
   const uint64_t physicsOrigin = m_physics->GetCurrentTime();
   auto fail = [&](const string& message) { bridge.Send("{\"error\":\"" + message + "\"}\n"); };
   auto waitFrame = [&]() {
      const uint64_t deadline = usec() + 30000000;
      while (rd->m_framePending || !rd->m_frameMutex.try_lock())
      {
         if (usec() > deadline) return false;
         uSleep(100);
      }
      FinishFrame();
      return true;
   };
   // Flush the startup frame before accepting any action.
   if (!waitFrame()) { fail("Startup render timeout"); SetCloseState(CS_CLOSE_APP); return; }
   rd->m_frameMutex.unlock();
   m_noTimeCorrect = false;

   CComPtr<IDispatch> script;
   m_scriptInterpreter->GetScriptDispatch(&script);
   OLECHAR observeName[] = L"RLObserve", actionName[] = L"RLApplyAction", tickName[] = L"RLTick", resetName[] = L"RLReset";
   LPOLESTR names[] = { observeName, actionName, tickName, resetName };
   DISPID ids[4];
   for (int i = 0; i < 4; ++i)
      if (!script || FAILED(script->GetIDsOfNames(IID_NULL, &names[i], 1, 0, &ids[i])))
      {
         fail("Table needs RLObserve, RLApplyAction, RLTick and RLReset script methods");
         SetCloseState(CS_CLOSE_APP); return;
      }
   DISPPARAMS noArgs = { nullptr, nullptr, 0, 0 };
   const char* gpuUUID = std::getenv("VPX_SELECTED_GPU_UUID");
   bridge.Send(std::format("{{\"protocol\":3,\"physics_tick_us\":{},\"renderer\":\"{}\",\"gpu_vendor_id\":{},\"gpu_device_id\":{},\"gpu_uuid\":\"{}\"}}\n",
      PHYSICS_STEPTIME, bgfx::getRendererName(bgfx::getRendererType()), bgfx::getCaps()->vendorId, bgfx::getCaps()->deviceId,
      gpuUUID ? gpuUUID : ""));
   string line;
   while (bridge.Receive(line))
   {
      if (line == "close") break;
      int count = 0;
      if (line == "reset")
      {
         // The render pipeline is drained before every response. Release any
         // active ball and its deferred table/script references before serving
         // the next one; this also supports resetting during a live episode.
         rd->m_frameMutex.lock();
         while (!m_vball.empty()) DestroyBall(m_vball.back());
         FinishFrame();
         rd->m_frameMutex.unlock();
         if (FAILED(script->Invoke(ids[3], IID_NULL, 0, DISPATCH_METHOD, &noArgs, nullptr, nullptr, nullptr)))
         { fail("RLReset failed"); break; }
         episodeOrigin = ticks; // Keep the engine/physics/timer clocks monotonic.
      }
      else
      {
         std::istringstream command(line);
         string op, extra;
         int left, right;
         if (!(command >> op >> left >> right >> count) || op != "step"
            || (command >> extra) || left < 0 || left > 1 || right < 0 || right > 1
            || count < 0 || count > 10000)
         { fail("Expected step left right ticks (bits, 0..10000 ticks), reset or close"); continue; }
         CComVariant actionArgs[] = { CComVariant(right), CComVariant(left) };
         DISPPARAMS actionParams = { actionArgs, nullptr, 2, 0 }; // COM arguments are reversed.
         if (FAILED(script->Invoke(ids[1], IID_NULL, 0, DISPATCH_METHOD, &actionParams, nullptr, nullptr, nullptr)))
         { fail("RLApplyAction failed"); break; }
      }
      bool scriptOK = true;
      for (int i = 0; i < count; ++i)
      {
         m_physics->StepExact();
         FireTimers(-2);
         ++ticks;
         if (FAILED(script->Invoke(ids[2], IID_NULL, 0, DISPATCH_METHOD, &noArgs, nullptr, nullptr, nullptr)))
         { scriptOK = false; break; }
      }
      if (!scriptOK) { fail("RLTick failed"); break; }
      if (m_physics->GetCurrentTime() - physicsOrigin != ticks * PHYSICS_STEPTIME)
      { fail("Physics tick count diverged"); break; }
      m_pluginManager.ProcessAsyncCallbacks();
      rd->m_frameMutex.lock();
      PrepareFrame();
      bridge.captureReady = false;
      bridge.captureRequested = true;
      SubmitFrame();
      const uint64_t deadline = usec() + 30000000;
      while (!bridge.captureReady && usec() < deadline) uSleep(100);
      if (!bridge.captureReady || !bridge.captureOK)
      { fail("RGB capture failed or timed out"); break; }
      if (!waitFrame()) { fail("Render timeout"); break; }
      rd->m_frameMutex.unlock();

      CComVariant state;
      if (FAILED(script->Invoke(ids[0], IID_NULL, 0, DISPATCH_METHOD, &noArgs, &state, nullptr, nullptr)) || state.vt != VT_BSTR)
      { fail("RLObserve failed"); break; }
      const string header = std::format("{{\"ticks\":{},\"width\":{},\"height\":{},\"bytes\":{},\"state\":{}}}\n",
         ticks - episodeOrigin, bridge.width, bridge.height, bridge.rgb.size(), MakeString(state.bstrVal));
      if (!bridge.Send(header) || !bridge.Send(bridge.rgb.data(), bridge.rgb.size())) break;
   }
   SetCloseState(CS_CLOSE_APP);
}
#endif
