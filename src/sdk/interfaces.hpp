#pragma once
//
// Version-agnostic interface capture. Every Source module keeps a singly linked
// list of InterfaceReg (name + factory). Instead of calling the exported
// CreateInterface with an exact version string ("VClient017"), we walk the list
// and match by name prefix ("VClient"), so the cheat survives engine updates.
//
#include <cstdint>
#include <string_view>
#include <windows.h>

#include "util/logger.hpp"

namespace lab::iface
{
    using InstantiateFn = void* (*)();

    // interface.h :: InterfaceReg
    struct InterfaceReg
    {
        InstantiateFn       create;
        const char*         name;
        InterfaceReg*       next;
    };

    // Resolve the head of a module's InterfaceReg list from its CreateInterface
    // export. On 32-bit MSVC builds the export is a small jmp/lea sequence that
    // references the static list head; we follow it.
    inline InterfaceReg* list_head(const char* module)
    {
        const HMODULE mod = GetModuleHandleA(module);
        if (!mod)
            return nullptr;

        auto create_interface = reinterpret_cast<std::uintptr_t>(GetProcAddress(mod, "CreateInterface"));
        if (!create_interface)
            return nullptr;

        // CreateInterface: jmp rel32 -> CreateInterfaceInternal
        // 0xE9 <rel32>
        if (*reinterpret_cast<std::uint8_t*>(create_interface) != 0xE9)
        {
            lab::log::info("interfaces: unexpected CreateInterface prologue in %s (verify build)", module);
            return nullptr;
        }

        const std::int32_t rel      = *reinterpret_cast<std::int32_t*>(create_interface + 1);
        const std::uintptr_t internal = create_interface + 5 + rel;

        // CreateInterfaceInternal references s_pInterfaceRegs via "mov reg, [imm32]"
        // Common encodings: A1 <imm32> (mov eax,[imm]) or 8B 0D/15/35 <imm32>.
        // Scan a short window for the absolute pointer load.
        for (std::uintptr_t p = internal; p < internal + 0x20; ++p)
        {
            const std::uint8_t op = *reinterpret_cast<std::uint8_t*>(p);
            std::uintptr_t imm_at = 0;
            if (op == 0xA1)                 // mov eax, [imm32]
                imm_at = p + 1;
            else if (op == 0x8B)            // mov reg, [imm32]  (modrm 0x0D/0x15/0x35)
                imm_at = p + 2;
            else
                continue;

            const auto pp = *reinterpret_cast<std::uintptr_t*>(imm_at);
            if (pp)
                return *reinterpret_cast<InterfaceReg**>(pp);
        }

        lab::log::info("interfaces: could not resolve InterfaceReg head in %s (verify signature)", module);
        return nullptr;
    }

    // Capture an interface by name prefix, e.g. capture("client.dll", "VClient").
    inline void* capture(const char* module, std::string_view prefix)
    {
        for (InterfaceReg* reg = list_head(module); reg; reg = reg->next)
        {
            if (std::string_view{ reg->name }.starts_with(prefix))
                return reg->create();
        }
        return nullptr;
    }

    // Dump every registered interface in a module — handy during recon.
    inline void dump(const char* module)
    {
        lab::log::info("interfaces in %s:", module);
        for (InterfaceReg* reg = list_head(module); reg; reg = reg->next)
            lab::log::info("  %s", reg->name);
    }
} // namespace lab::iface
