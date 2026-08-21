# Handoff — items vs entities separation (WIP, follow-up on the /inventory + emoji work)

> **UPDATE (2026-08-19):** the foundation AND the "Remaining" items below are
> now implemented and the suite is green — see `docs/ITEMS.md`. `/frog
> consume` retired in favor of `/inventory consume`; `Species` sheds its
> consume fields; the frog renderer registry is removed (`/inventory`
> renders via `bot.items`). Only the settings-backed `items_consumable`
> override (Remaining #5) is intentionally left as a code-level `Plugin`
> attribute for now.

Status as of this session. Read this first in a fresh context; everything below
is the current truth of the **items/entities (frogs) separation** refactor.

## What this work is

Separating the game's two player-visible concepts, in the frogs plugin first:

- **Entity** (a frog) — a world/spawn object with its own behavior (spawn
  cadence, catch effect). Catching one grants items.
- **Item** — a stackable inventory object (immutable item_id oracle, display
  name, icon, item-owned consume behavior).

Consumption moves off the species/entity onto the **item**. Inventory becomes
a definitions layer (`bot.items`) on top of the already-generic ledger
(`bot.inventory`).

## Decisions locked in

- **Two flags per items-provider (plugin), independent:**
  - `enabled` (existing) — gates **behavior**: spawns, on_message, catch
    buttons, the plugin's own command tree.
  - `items_consumable` (new `Plugin` attr) — gates whether that plugin's
    items **can be consumed**. Holdings stay visible either way; only consume
    is gated. Item definitions resolve by id **independent of enablement**, so
    disabling behavior keeps existing holdings visible/consumable via the
    always-present `/inventory consume`. Only true code removal (id unregistered)
    → `NOOP` (hidden, refused).
- **Item ids are the immutable oracle**: enum member = code reference (rename
  freely); value carries an explicit immutable `item_id` string; mutable
  `display_name`. Frog item ids match the **legacy stored strings**
  (`frog:leaf_frog:normal`, …) → **no DB migration**.
- **Inventory API** is explicit: `add` (+1 pick-up), `remove` (−1 drop), and a
  general `modify` for arbitrary deltas.
- **`/inventory` becomes a group**: `/inventory view` (emoji-only grid via the
  item registry) + `/inventory consume <slot>` (generic, item-owned consume).
  `/frog consume` still exists (not yet retired — see Remaining).

## What's implemented and verified (full suite = 636 green)

- **`cazzubot/items.py`** (new) — `Item` (item_id/display_name/icon/consume),
  `NOOP` sentinel, module registry `register_items`/`unregister_items`/
  `item_for`/`set_consumable`/`consumable`, and the `Items` service
  (`bot.items`). Registry is module-global; exposed as `bot.items`.
- **`cazzubot/plugin.py`** — added `item_decl: type[Enum] | None` and
  `items_consumable: bool = True`.
- **`cazzubot/bot.py`** — wires `self.items`; on boot and in `load_plugin`/
  `unload_plugin`, registers/unregisters each plugin's `item_decl` and sets its
  consumable flag (independent of behavior enablement).
- **`cazzubot/inventory.py`** — `add`/`remove`/`modify` primitives + service
  methods (modify is the general signed-delta; add/remove default qty=1).
- **`plugins/frogs/items.py`** (new) — `FrogItems` enum: leaf/classy ×
  normal/frozen frog items, ids = legacy strings, each with item-owned consume
  granting seasonal exp (leaf 10/3, classy 20/6). Registered as the frogs
  plugin's `item_decl`.
- **`plugins/frogs/__init__.py`** — `item_decl = FrogItems` (auto-registered by
  bot.py).
- **`plugins/frogs/factory.py`** — catch now grants the matching frog item via
  `bot.inventory.add` when `species.catch_effect is None` (default "catch grants
  the item"); a custom `catch_effect` owns the behavior instead. Also fixed
  `_frog_content` (spawn text) to fall back to the name when the emoji asset
  isn't published (was printing "None").
- **`plugins/inventory/extension.py`** — `inventory` Group with `view`
  (emoji-only numbered grid rendered from `bot.items.item_for(id)`; unresolved
  ids hidden) and `consume <slot> [amount]` (resolves the slot, checks the
  provider's `consumable` flag, confirm-menu, then runs `item.consume` and
  reduces the stack). `loader.command(inventory)` added.
- **Tests**: `tests/core/test_items.py` (registry, NOOP, consumable flag),
  `tests/integration/test_inventory_driver.py` (view grid, empty, consume runs
  item-owned exp grant + stack reduction, empty-slot reject), and command-guard
  allowlist updated to `("inventory","view")` + `("inventory","consume")`.
- Fixed two pre-existing failures from the user's committed emoji patch
  (spawn "None" content; stale inventory-driver label assertion).

## How the pieces fit (fresh-context orientation)

- Item *definitions* are code: a plugin sets `item_decl = SomeEnum`
  (`member.value` is an `Item`). `bot.py` registers them at load and
  unregisters at unload; `bot.items.item_for(id)` resolves them at read/use
  time, `bot.items.consumable(id)` gates consumption.
- The *ledger* (`inventory` table) is unchanged and counts by item_id string.
- `/inventory view` renders each non-empty stack by resolving its id to an
  Item's emoji icon. `/inventory consume <slot>` addresses a stack by its
  derived slot number (deterministic `ORDER BY item`), runs the item's
  consume handler, then `bot.inventory.remove`.

## Remaining (NOT done — next unit of work)

1. **Slim `Species`** (the entity): remove the now-redundant `consume_effect`
   and `consumable` fields — consume is item-owned. Keep `catch_effect` (defines
   what happens on catch). This will break `/frog consume`, `/frog catalog`, and
   `/frog profile` (they read `species.consume_effect`); update them accordingly.
2. **Retire `/frog consume`** in favor of `/inventory consume` (plan: it
   replaces `/frog consume`). Update the frog extension (remove the Consume
   command) + `test_confirm_menu_driver.test_frog_consume_confirm` + command
   guard. Decide whether the frog-specific `FrogConsumedEvent` should still fire
   from the generic path (the generic consume currently doesn't emit it — a gap
   for the future badge system).
3. **Remove the now-redundant `frog_renderer`** and the renderer registry in
   `cazzubot/inventory.py` (register_renderer/unregister_renderer/renderer_for/
   ItemView) — `/inventory` now renders via `bot.items`, so the renderer path is
   dead. Remove the frogs `on_load` `register_renderer("frog", …)`.
4. **Docs**: a short `docs/ITEMS.md` capturing the item-vs-entity model and the
   two-flag deprecation story; update `docs/PLUGINS.md` (`bot.items`, item_decl,
   the `/inventory` group, add/remove/modify), `docs/ROADMAP.md`/`docs/BACKLOG.md`
   (entity↔item lexicon; note the two-flag "deprecate behavior, keep items").
5. Consider a settings-backed override for `items_consumable` (currently a
   code-level `Plugin` attr only) mirroring `plugin.enabled.<name>`.

## Environment notes (unchanged)

- Emoji publishing needs `ASSET_GUILD_ID` / `ASSET_CHANNEL_ID` in `.env` and the
  bot joined to the asset guild; otherwise emoji rows are skipped (boot warning)
  and `bot.assets.get` returns None → spawn text falls back to the name.
- Guild safety: sandbox guild `408801760581386245` is free to mutate; production
  `293796316193095690` is never mutated without explicit per-turn permission.
- `/inventory view|consume` are public/user-facing (in `USER_FACING`).

## Commands

- Full suite: `uv run pytest` (636 passing).
- Lint: `uv run ruff check .` — Types: `uv run basedpyright`.
- Tests for this work: `tests/core/test_items.py`,
  `tests/integration/test_inventory_driver.py`, `tests/core/test_command_guards.py`,
  `tests/plugins/frogs/`.
