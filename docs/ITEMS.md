# Items vs Entities

The game distinguishes two player-visible concepts, kept apart so each can
evolve independently:

- **Entity** — a world/spawn object with its own behavior (spawn cadence,
  catch effect). Catching one grants items. Today the only entity is a frog
  (`plugins/frogs/species.py` — `Species`).
- **Item** — a stackable inventory object with an immutable `item_id` oracle,
  a display name/icon, and an **item-owned consume** behavior
  (`cazzubot/items.py` — `Item`; `plugins/frogs/items.py` — `FrogItems`).

Both share the same generic ledger (`cazzubot/inventory.py`, the `inventory`
table) but live at very different layers: the **definitions** of items are
code, and the **ledger** only counts holdings by their stored `item_id`.

## The layering

```
┌──────────────────────────────────────────────────────────────┐
│ bot.inventory  — the ledger: (uid, item_id, qty) rows only    │
│   add / remove / modify, get / rows / total / move_all        │
│   knows nothing about what an item IS                         │
├──────────────────────────────────────────────────────────────┤
│ bot.items  — the definitions layer: item_id → Item            │
│   (icon, display_name, item-owned consume)                    │
│   resolves by id independent of plugin enablement             │
├──────────────────────────────────────────────────────────────┤
│ plugin.item_decl  — a plugin declares its items as an enum    │
│   each member.value is an Item; the item_id IS the oracle     │
└──────────────────────────────────────────────────────────────┘
```

`bot.py` registers a plugin's `item_decl` with `bot.items` at plugin load and
unregisters it at unload, and sets its `items_consumable` flag — both
**independent of the `enabled` behavior flag**.

## The two-flag deprecation story

Whether a game feature "still works" splits into two independent decisions:

- `plugin.enabled.<name>` (settings) / `Plugin.enabled` (code) — gates
  **behavior**: spawns, `on_message` hooks, catch buttons, the plugin's own
  command tree. Disabling it stops new items from appearing.
- `Plugin.items_consumable` (code attr) — gates whether that plugin's items
  **can be consumed**. Holdings stay visible either way.

This is deliberate: **deprecating a behavior does not take its items out of
inventory.** A plugin can be behavior-disabled (no more spawning/commands)
while its existing holdings remain visible and consumable through the
always-present generic `/inventory view` and `/inventory consume`. Item
definitions resolve by id independent of enablement, so only **true code
removal** (an `item_id` no longer registered) drops an item to `NOOP` —
hidden from the grid, refused consumption.

## Item ids are the immutable oracle

- The enum **member** is the code reference — rename it freely.
- The member's **value** carries an explicit, immutable `item_id` string.
- The ledger stores that exact string (in `inventory.item`), so renaming a
  member or changing `display_name` never touches stored data. Changing an
  `item_id` is a migration.
- Frog item ids match the **legacy stored strings** (`frog:leaf_frog:normal`,
  …) byte-for-byte, so the entity→item split required **no DB migration**.

## Consumption

Consumption is **item-owned**, not entity-owned:

- `Item.consume` is an optional `async (bot, uid, amount) -> None` handler.
- `/inventory consume <slot> [amount]` resolves the slot to its `item_id`,
  checks the provider's `items_consumable` flag, confirms, then runs
  `item.consume` and decrements the stack (`bot.inventory.remove`).
- A species carries no consume data (it keeps only `catch_effect`); the
  inventory tooling is fully generic and never knows what an item's consume
  does.

Domain observability stays alive: a frog item's consume handler grants the
seasonal exp and emits a `FrogConsumedEvent` on `bot.events`, so a future
badge system can observe consumption without the generic consume path knowing
about frogs.

## The inventory API (summary)

Ledger primitives on `bot.inventory` / `cazzubot.inventory`:

- `add(uid, item[, amount=1])` — pick up.
- `remove(uid, item[, amount=1])` — drop.
- `modify(uid, item, amount)` — arbitrary signed delta (prunes at ≤ 0).
- `get` / `rows` / `rows_indexed` / `total` / `move_all` — read side and the
  quarterly freeze primitive.

An `item` argument is either a typed identity exposing `.key` (e.g. the
frogs `FrogItem`) or a raw stored string — the two are interchangeable.

## Commands

- `/inventory view [user]` — numbered inline-emoji grid (item icons).
- `/inventory consume <slot> [amount]` — generic, item-owned consume.
- `/frog catalog` — reports each species' per-state consume value from its
  item definitions (the entity itself carries no consume data).
