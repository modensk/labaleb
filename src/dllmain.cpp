//
// labaleb — HL2 singleplayer speedrun trainer (Source SDK 2013, x86).
//
// Milestone 1 (this file): load into hl2.exe, spin up a worker thread, capture
// the client interface version-agnostically, build the netvar map, and prove we
// can resolve player offsets (velocity / flags / movetype) by NAME with no
// hardcoded offsets. Hooks, movement and the ImGui menu come next.
//
#include <windows.h>

#include "util/logger.hpp"
#include "sdk/interfaces.hpp"
#include "sdk/netvars.hpp"
#include "sdk/sdk_types.hpp"

namespace
{
    HMODULE g_self = nullptr;

    void run()
    {
        lab::log::open_console("labaleb — loaded");
        lab::log::info("injected into hl2.exe, starting recon...");

        // 1) Capture the client interface by prefix (no exact version needed).
        auto* client = static_cast<lab::sdk::IBaseClientDLL*>(
            lab::iface::capture("client.dll", "VClient"));

        if (!client)
        {
            lab::log::info("FATAL: could not capture VClient — dumping interfaces:");
            lab::iface::dump("client.dll");
            return;
        }
        lab::log::info("captured IBaseClientDLL @ %p", client);

        // 2) Build the netvar map from the ClientClass list.
        lab::sdk::ClientClass* head = client->GetAllClasses();
        if (!head)
        {
            lab::log::info("FATAL: GetAllClasses() returned null — verify kIdx_GetAllClasses");
            return;
        }
        lab::netvars::g_netvars.build(head);

        // 3) Prove offsets resolve by name (these are what bhop/noclip will use).
        lab::log::info("resolved offsets:");
        lab::log::info("  DT_BasePlayer::m_vecVelocity[0] = 0x%X",
                       lab::netvars::g_netvars.get("DT_BasePlayer", "m_vecVelocity[0]"));
        lab::log::info("  DT_BasePlayer::m_fFlags         = 0x%X",
                       lab::netvars::g_netvars.get("DT_BasePlayer", "m_fFlags"));
        lab::log::info("  DT_BaseEntity::m_flMaxspeed     = 0x%X",
                       lab::netvars::g_netvars.get("DT_BasePlayer", "m_flMaxspeed"));

        lab::log::info("recon done. press END in the console to unload.");

        // Idle until the user asks to unload (next milestones add the menu/hooks).
        while (!(GetAsyncKeyState(VK_END) & 1))
            Sleep(50);

        lab::log::info("unloading...");
        lab::log::close_console();
        FreeLibraryAndExitThread(g_self, 0);
    }
} // namespace

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID /*reserved*/)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        g_self = module;
        DisableThreadLibraryCalls(module);
        if (HANDLE t = CreateThread(nullptr, 0,
                                    [](LPVOID) -> DWORD { run(); return 0; },
                                    nullptr, 0, nullptr))
            CloseHandle(t);
    }
    return TRUE;
}
