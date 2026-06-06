# Разведка движка Source (HL2 SP) — база знаний проекта

Документ описывает, **что** мы хукаем и читаем, **где** это лежит в движке и **как**
находить адреса. Конкретные байтовые сигнатуры/оффсеты заполняем уже по живому
`hl2.exe` нужной версии (они плавают между билдами), здесь — стабильная карта.

Цель — классический 32-битный Source (ветка Source SDK 2013 mp/sp). Всё ниже —
публично известная структура движка из открытого Source SDK.

---

## 1. Модули процесса
HL2 загружает игру набором DLL. Нам важны:

| Модуль            | Что внутри |
|-------------------|-----------|
| `engine.dll`      | `IVEngineClient` (ввод, локальный игрок, трассировки), сетевой/локальный стейт |
| `client.dll`      | клиентская игра: `IBaseClientDLL`, `IClientEntityList`, прогноз движения, `CreateMove` |
| `vstdlib.dll`     | `ICvar` — доступ к консольным переменным/командам |
| `vguimatsurface.dll` / `materialsystem.dll` | рендер, отсюда выходим на DX9 device для оверлея |
| `shaderapidx9.dll`| держит `IDirect3DDevice9` — точка хука для ImGui (EndScene/Present) |

Все игровые DLL экспортируют **`CreateInterface`** — фабрику для получения
интерфейсов по строковому имени (версии в имени: например `VEngineClient014`).

---

## 2. Ключевые интерфейсы (получаем через CreateInterface)

| Интерфейс | Версия (примерно) | Откуда | Зачем |
|-----------|-------------------|--------|-------|
| `IVEngineClient`      | `VEngineClient0xx`     | engine.dll | `GetLocalPlayer()` (индекс), `GetViewAngles`, `IsInGame`, трассировки |
| `IBaseClientDLL`      | `VClient0xx`           | client.dll | вход к `CreateMove`, HUD, прогноз |
| `IClientEntityList`   | `VClientEntityList003` | client.dll | `GetClientEntity(index)` → указатель на энтити игрока |
| `ICvar`               | `VEngineCvar0xx`       | vstdlib.dll| читать/менять `sv_cheats`, `sv_friction`, `sv_maxspeed`, регать свои cvar |
| `IClientMode` (ClientModeShared) | через client.dll | client.dll | альтернативная точка хука `CreateMove` |

> Версии интерфейсов уточняем дампом экспортов конкретного билда (strings/IDA).

---

## 3. Локальный игрок
Путь до игрока:

```
int idx = engine->GetLocalPlayer();          // индекс локального игрока
IClientEntity* ent = entitylist->GetClientEntity(idx);
// ent -> наш C_BasePlayer
```

От `C_BasePlayer` читаем поля по **оффсетам netvar/datamap**. Имена полей стабильны,
оффсеты — нет, поэтому ищем их через netvar-дамп или datamap.

### Нужные поля
| Поле (netvar/datamap) | Тип | Назначение |
|-----------------------|-----|-----------|
| `m_vecVelocity[0]`    | Vector | текущая скорость — читаем для индикатора, пишем для буста |
| `m_vecAbsOrigin`      | Vector | позиция игрока |
| `m_fFlags`            | int    | флаги; бит `FL_ONGROUND (1<<0)` — на земле ли (ключ для bhop) |
| `m_MoveType`          | int    | тип движения; `MOVETYPE_NOCLIP (8)` — для noclip |
| `m_flMaxspeed`        | float  | потолок скорости игрока |

`FL_ONGROUND` и `m_MoveType` — фундамент для bhop и noclip соответственно.

---

## 4. Bhop — точка перехвата
В одиночном Source движение прогоняется клиентом каждый тик через **CreateMove**,
который заполняет `CUserCmd` (кнопки игрока этого тика).

**План хука:**
- Хукаем `IBaseClientDLL::CreateMove` (или `ClientModeShared::CreateMove`).
- В хуке у нас есть `CUserCmd*` с полем `buttons` (битмаска `IN_*`).
- Логика bhop:
  1. читаем `m_fFlags & FL_ONGROUND`;
  2. если игрок **держит** `IN_JUMP` и **сейчас на земле** — оставляем прыжок;
  3. если в воздухе — снимаем бит `IN_JUMP` (чтобы движок «принял» прыжок ровно
     в кадр касания земли и не сбрасывал скорость трением).

Кнопки `CUserCmd`:
| Бит        | Значение |
|------------|----------|
| `IN_JUMP`  | `1 << 1` |
| `IN_DUCK`  | `1 << 2` |
| `IN_FORWARD` `IN_BACK` `IN_MOVELEFT` `IN_MOVERIGHT` | направления для авто-стрейфа/ABH |

---

## 5. Набор скорости
Два метода, оба валидны для спидрана:
- **ABH (Accelerated BackHopping)** — естественный разгон спиной вперёд. Через тот же
  `CreateMove`: на земле жмём назад + прыжок, в воздухе чуть доворачиваем — Source
  складывает скорость. Автоматизируем угол/кнопки.
- **Прямой буст** — пишем в `m_vecVelocity` или временно поднимаем `m_flMaxspeed` /
  правим `sv_friction` через `ICvar`. Грубее, но мгновенно.

---

## 6. Noclip / прохождение сквозь стены
- Простейшее: выставить `m_MoveType = MOVETYPE_NOCLIP (8)` на игроке (требует
  контекста `sv_cheats`, в SP доступно). Тумблер в меню.
- Спидран-трюки (save/load glitch, стак на пропах/«бочки») — поздний этап, требует
  работы с энтити пропов через `IClientEntityList`.

---

## 7. ImGui-оверлей
- HL2 (старый движок) рендерит через **DirectX 9**.
- Хукаем `IDirect3DDevice9::EndScene` (или `Present`) через vtable-хук.
- Инициализируем ImGui DX9 backend, рисуем меню; ввод — через хук `WndProc`.
- Меню: тумблеры (Bhop / Noclip / AutoStrafe), слайдеры (целевая скорость), индикатор
  текущей скорости и позиции.

---

## 8. Чек-лист разведки по живому билду (следующий шаг)
- [ ] Определить версию `hl2.exe` и точные версии интерфейсов (дамп экспортов).
- [ ] Снять netvar-дамп → оффсеты `m_vecVelocity`, `m_fFlags`, `m_MoveType`, `m_flMaxspeed`.
- [ ] Найти сигнатуру `CreateMove`.
- [ ] Найти vtable `IDirect3DDevice9` (индексы EndScene/Present).
- [ ] Подтвердить `CreateInterface` экспорт в каждом модуле.

> Конкретные байты/оффсеты складываем в отдельный `offsets.h` на этапе скелета —
> чтобы при смене билда менять в одном месте.
