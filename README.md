# labaleb — HL2 Speedrun Trainer (Singleplayer)

Внутренний (internal) DLL-тренажёр для **одиночного** Half-Life 2 на движке Source.
Цель — инструменты для спидрана: bunny hop, набор скорости (ABH), noclip / прохождение
сквозь геометрию. ImGui-оверлей для управления.

> ⚠️ Только синглплеер. Никакой работы с мультиплеерными серверами и анти-читами.
> Это аналог практических тулз вроде SourcePauseTool — для тренировки трюков на локалке.

## Стек
- **C++**, MSVC, сборка **x86 DLL** (классический 32-бит Source engine / SDK 2013)
- **MinHook** — перехват функций движка
- **ImGui** (DX9 backend) — оверлей-меню
- Инжект — простой LoadLibrary-инжектор

## Статус
- [x] Разведка движка — см. [`docs/RECON.md`](docs/RECON.md)
- [x] Скелет проекта (DllMain + лог + динамический резолв оффсетов)
- [ ] Доступ к локальному игроку, читалка скорости (на экран)
- [ ] Bhop (хук CreateMove)
- [ ] Набор скорости / ABH
- [ ] Noclip / wallclip
- [ ] ImGui-меню + хоткеи

## Сборка
Цель — 32-битная DLL под `hl2.exe` (Source SDK 2013). Нужен MSVC + CMake.

```
cmake -B build -A Win32
cmake --build build --config Release
```

На выходе `labaleb.dll`. Инжектится любым x86-инжектором (LoadLibrary) в `hl2.exe`.
После инжекта появится консоль с дампом отрезолвленных netvar-оффсетов; `END` — выгрузка.

> Собирается только на Windows/x86. Линукс-хост DLL под игру не даст.

## Структура
```
src/
  dllmain.cpp        — точка входа, поток, recon-пайплайн
  util/logger.hpp    — лог в консоль + OutputDebugString
  sdk/
    memory.hpp       — модули + pattern scanner (IDA-style сигнатуры)
    interfaces.hpp   — walk InterfaceReg (интерфейсы по префиксу имени)
    sdk_types.hpp    — layout'ы RecvProp/RecvTable/ClientClass + enum'ы
    netvars.{hpp,cpp}— netvar-менеджер: оффсеты по имени
```

## Roadmap
Подробности в `docs/RECON.md`. Каждый пункт roadmap = отдельный коммит.
