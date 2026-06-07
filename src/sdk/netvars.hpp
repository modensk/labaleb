#pragma once
//
// Netvar manager. Walks the engine's ClientClass -> RecvTable -> RecvProp graph
// once at startup and builds a "DT_Table -> prop name -> offset" map. Lets us
// read player fields (velocity, flags, movetype, ...) by name with zero
// hardcoded offsets, so the cheat works across Source SDK 2013 builds.
//
#include <cstdint>
#include <string>
#include <unordered_map>

#include "sdk/sdk_types.hpp"

namespace lab::netvars
{
    class Manager
    {
    public:
        // Build the table from the client.dll ClientClass list head.
        void build(sdk::ClientClass* head);

        // Offset of a prop within its table, e.g. get("DT_BasePlayer", "m_fFlags").
        // Returns 0 if not found (also logs a warning on build for misses).
        [[nodiscard]] std::uint32_t get(const std::string& table, const std::string& prop) const;

        [[nodiscard]] std::size_t table_count() const { return tables_.size(); }

    private:
        void walk_table(const sdk::RecvTable* table);

        // table name -> (prop name -> offset)
        std::unordered_map<std::string, std::unordered_map<std::string, std::uint32_t>> tables_;
    };

    // Global instance, initialised in dllmain.
    inline Manager g_netvars;
} // namespace lab::netvars
