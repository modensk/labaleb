#pragma once
//
// Tiny logging helper. Writes to an allocated console and to the debugger
// (OutputDebugString), so output is visible both in the spawned console and in
// a tool like DebugView while the cheat is loaded inside hl2.exe.
//
#include <cstdio>
#include <string>
#include <windows.h>

namespace lab::log
{
    // Allocate a console window for the host process and bind stdio to it.
    inline void open_console(const char* title = "labaleb")
    {
        if (AllocConsole())
        {
            FILE* dummy = nullptr;
            freopen_s(&dummy, "CONOUT$", "w", stdout);
            freopen_s(&dummy, "CONOUT$", "w", stderr);
            SetConsoleTitleA(title);
        }
    }

    inline void close_console()
    {
        FreeConsole();
    }

    template <typename... Args>
    inline void info(const char* fmt, Args... args)
    {
        char buf[1024];
        std::snprintf(buf, sizeof(buf), fmt, args...);

        std::printf("[labaleb] %s\n", buf);

        OutputDebugStringA("[labaleb] ");
        OutputDebugStringA(buf);
        OutputDebugStringA("\n");
    }
} // namespace lab::log
