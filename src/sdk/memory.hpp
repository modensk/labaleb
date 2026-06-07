#pragma once
//
// Module + pattern-scanning helpers. Used to locate engine functions that are
// not reachable through netvars or the interface list (e.g. CreateMove), and to
// resolve module bases for the interface walker.
//
#include <cstdint>
#include <string_view>
#include <vector>
#include <optional>
#include <windows.h>
#include <psapi.h>

namespace lab::mem
{
    struct Module
    {
        std::uintptr_t base = 0;
        std::size_t    size = 0;

        [[nodiscard]] bool valid() const { return base != 0 && size != 0; }
    };

    // Resolve a loaded module by name, e.g. "client.dll".
    inline Module get_module(const char* name)
    {
        const HMODULE handle = GetModuleHandleA(name);
        if (!handle)
            return {};

        MODULEINFO info{};
        if (!GetModuleInformation(GetCurrentProcess(), handle, &info, sizeof(info)))
            return {};

        return { reinterpret_cast<std::uintptr_t>(info.lpBaseOfDll), info.SizeOfImage };
    }

    // Parse an IDA-style signature ("A1 ?? ?? ?? ?? 8B") into bytes + mask.
    inline void parse_signature(std::string_view sig,
                                std::vector<std::uint8_t>& bytes,
                                std::vector<bool>& mask)
    {
        for (std::size_t i = 0; i < sig.size();)
        {
            if (sig[i] == ' ')
            {
                ++i;
                continue;
            }

            if (sig[i] == '?')
            {
                bytes.push_back(0);
                mask.push_back(false); // wildcard
                i += (i + 1 < sig.size() && sig[i + 1] == '?') ? 2 : 1;
            }
            else
            {
                bytes.push_back(static_cast<std::uint8_t>(std::strtoul(sig.data() + i, nullptr, 16)));
                mask.push_back(true);
                i += 2;
            }
        }
    }

    // Scan a module for an IDA-style signature. Returns the matching address.
    inline std::optional<std::uintptr_t> find_pattern(const Module& mod, std::string_view sig)
    {
        if (!mod.valid())
            return std::nullopt;

        std::vector<std::uint8_t> bytes;
        std::vector<bool>         mask;
        parse_signature(sig, bytes, mask);
        if (bytes.empty())
            return std::nullopt;

        const auto* const region = reinterpret_cast<const std::uint8_t*>(mod.base);
        const std::size_t last    = mod.size - bytes.size();

        for (std::size_t i = 0; i <= last; ++i)
        {
            bool hit = true;
            for (std::size_t j = 0; j < bytes.size(); ++j)
            {
                if (mask[j] && region[i + j] != bytes[j])
                {
                    hit = false;
                    break;
                }
            }
            if (hit)
                return mod.base + i;
        }
        return std::nullopt;
    }
} // namespace lab::mem
