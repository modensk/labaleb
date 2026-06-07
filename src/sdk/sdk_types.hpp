#pragma once
//
// Minimal Source SDK 2013 type layouts that we rely on. These mirror the public
// Source SDK headers (dt_recv.h, cdll_int.h). Only the fields we read are kept;
// trailing members are omitted because we always touch these through pointers.
//
#include <cstdint>

namespace lab::sdk
{
    class RecvTable; // fwd

    // dt_recv.h :: RecvProp
    class RecvProp
    {
    public:
        const char* m_pVarName;        // property name, e.g. "m_vecVelocity[0]"
        int         m_RecvType;        // SendPropType
        int         m_Flags;
        int         m_StringBufferSize;
        bool        m_bInsideArray;
        const void* m_pExtraData;
        RecvProp*   m_pArrayProp;
        void*       m_ArrayLengthProxy;
        void*       m_ProxyFn;
        void*       m_DataTableProxyFn;
        RecvTable*  m_pDataTable;       // non-null for nested DataTable props
        int         m_Offset;          // offset of this prop within the class
        int         m_ElementStride;
        int         m_nElements;
        const char* m_pParentArrayPropName;
    };

    // dt_recv.h :: RecvTable
    class RecvTable
    {
    public:
        RecvProp*   m_pProps;
        int         m_nProps;
        void*       m_pDecoder;
        const char* m_pNetTableName;    // e.g. "DT_BasePlayer"
        bool        m_bInitialized;
        bool        m_bInMainList;
    };

    // client_class.h :: ClientClass (singly linked list of networked classes)
    class ClientClass
    {
    public:
        void*        m_pCreateFn;
        void*        m_pCreateEventFn;
        const char*  m_pNetworkName;    // e.g. "CBasePlayer"
        RecvTable*   m_pRecvTable;
        ClientClass* m_pNext;
        int          m_ClassID;
    };

    // cdll_int.h :: IBaseClientDLL — only GetAllClasses, reached via vtable.
    //
    // NOTE: the vtable index of GetAllClasses varies slightly between builds.
    // Verify against the live client.dll and adjust kIdx_GetAllClasses.
    class IBaseClientDLL
    {
    public:
        // index into IBaseClientDLL's vtable for GetAllClasses()
        static constexpr int kIdx_GetAllClasses = 8; // TODO: verify per build

        ClientClass* GetAllClasses()
        {
            using Fn          = ClientClass*(__thiscall*)(void*);
            auto** const vt   = *reinterpret_cast<void***>(this);
            auto   const func = reinterpret_cast<Fn>(vt[kIdx_GetAllClasses]);
            return func(this);
        }
    };

    // Player flags (const.h)
    enum PlayerFlags : int
    {
        FL_ONGROUND = (1 << 0),
        FL_DUCKING  = (1 << 1),
    };

    // MoveType (const.h)
    enum MoveType : int
    {
        MOVETYPE_WALK   = 2,
        MOVETYPE_NOCLIP = 8,
    };

    // CUserCmd button bits (in_buttons.h)
    enum Buttons : int
    {
        IN_JUMP      = (1 << 1),
        IN_DUCK      = (1 << 2),
        IN_FORWARD   = (1 << 3),
        IN_BACK      = (1 << 4),
        IN_MOVELEFT  = (1 << 9),
        IN_MOVERIGHT = (1 << 10),
    };
} // namespace lab::sdk
