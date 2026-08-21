# How do I... add a new item

An **item** is a stackable inventory object a member can hold and (optionally)
consume — for example a frog. Items are **defined in code** as an enum; the
actual counts live in a generic ledger (`bot.inventory`, the `inventory`
table). See `docs/needs-rewrite/ITEMS.md` for the full design.

Every item has:

- an immutable **`item_id`** (the string stored in the ledger — renaming it
  is a migration), and
- a `display_name` and `icon` (an emoji tag or URL shown in `/inventory`), and
- an optional **`consume`** behavior.

This example adds a **`gold_coin`** item to a `badges` plugin.

## 1. Define the item

`plugins/badges/items.py`:

```python
from enum import Enum

from cazzubot import Item


class BadgeItems(Enum):
    GOLD_COIN = Item(
        item_id="badge:gold_coin",
        display_name="Gold Coin",
        icon="🪙",
        consume=None,  # not directly consumable
    )
```

Keep `item_id` stable and unique — it's the durable oracle stored in
`inventory.item`. You can rename the enum member freely; never rename the
`item_id` without a migration.

## 2. Wire it into the plugin

In `plugins/badges/__init__.py`:

```python
from .items import BadgeItems

class BadgesPlugin(Plugin):
    name = "badges"
    ...
    item_decl = BadgeItems
```

`bot.py` registers the enum with `bot.items` at load and unregisters it at
unload automatically.

## 3. Give and take items

Use the generic ledger (`bot.inventory`):

```python
from .items import BadgeItems

# grant one
await bot.inventory.add(uid, BadgeItems.GOLD_COIN)

# take/grant a signed amount
await bot.inventory.modify(uid, BadgeItems.GOLD_COIN, -1)
```

Members see items in `/inventory view` automatically.

## 4. Make it consumable (optional)

Give the item a `consume` handler and enable consumption:

```python
async def _consume_coin(bot, uid, amount) -> None:
    # item-owned consume behavior, e.g. grant exp
    ...

class BadgeItems(Enum):
    GOLD_COIN = Item(
        item_id="badge:gold_coin",
        display_name="Gold Coin",
        icon="🪙",
        consume=_consume_coin,
    )
```

Then in the plugin:

```python
class BadgesPlugin(Plugin):
    name = "badges"
    item_decl = BadgeItems
    items_consumable = True   # the default
```

`/inventory consume <slot> [amount]` resolves the item, checks the provider's
`items_consumable` flag, asks for confirmation, runs your `consume` handler,
and decrements the stack.

## Notes

- The `enabled` behavior flag and `items_consumable` are **independent** — a
  plugin can be behavior-disabled while its holdings stay visible and
  consumable (or vice versa). Disabling a plugin never takes existing items
  out of inventory.
- Item ids resolve even if a plugin is disabled, as long as its module is
  still present. Only true code removal drops an item to `NOOP` (hidden,
  non-consumable).
