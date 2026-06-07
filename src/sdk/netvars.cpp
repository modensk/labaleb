#include "sdk/netvars.hpp"

#include "util/logger.hpp"

namespace lab::netvars
{
    void Manager::walk_table(const sdk::RecvTable* table)
    {
        if (!table || !table->m_pNetTableName)
            return;

        auto& props = tables_[table->m_pNetTableName];

        for (int i = 0; i < table->m_nProps; ++i)
        {
            const sdk::RecvProp& prop = table->m_pProps[i];
            if (!prop.m_pVarName)
                continue;

            // Skip the array-internals "baseclass"/numeric proxies that carry no
            // useful name.
            if (prop.m_pVarName[0] >= '0' && prop.m_pVarName[0] <= '9')
                continue;

            props[prop.m_pVarName] = static_cast<std::uint32_t>(prop.m_Offset);

            // Recurse into nested DataTables (the offset of the parent prop is
            // added when callers resolve nested names; for now we flatten by
            // table, which is enough for the fields we need).
            if (prop.m_pDataTable && prop.m_pDataTable->m_nProps > 0)
                walk_table(prop.m_pDataTable);
        }
    }

    void Manager::build(sdk::ClientClass* head)
    {
        tables_.clear();

        int classes = 0;
        for (sdk::ClientClass* cc = head; cc; cc = cc->m_pNext)
        {
            walk_table(cc->m_pRecvTable);
            ++classes;
        }

        lab::log::info("netvars: parsed %d classes, %zu tables", classes, tables_.size());
    }

    std::uint32_t Manager::get(const std::string& table, const std::string& prop) const
    {
        const auto t = tables_.find(table);
        if (t == tables_.end())
        {
            lab::log::info("netvars: table not found: %s", table.c_str());
            return 0;
        }

        const auto p = t->second.find(prop);
        if (p == t->second.end())
        {
            lab::log::info("netvars: prop not found: %s::%s", table.c_str(), prop.c_str());
            return 0;
        }
        return p->second;
    }
} // namespace lab::netvars
