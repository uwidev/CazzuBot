How do I… grant & consume items at runtime
==========================================

Items you grant or consume at runtime ride the generic inventory.
`bot.inventory` is the `(uid, item, qty)` ledger; `bot.items` holds the
definitions. Add a definition first (see **add a new item**), then move
counts here.


1. Grant
--------

~~~~ python
await bot.inventory.add(uid, item_id, amount=1)
~~~~

`add` is a positive delta. The frogs flow grants a capture exactly this way:

~~~~ python
await bot.inventory.add(uid, FrogItem(species_key, state))
~~~~

`item_id` may be a string key or a typed `InventoryKey` (enum member) whose
`.key` is the durable storage string.


2. Read a stack
---------------

~~~~ python
count = await bot.inventory.get(uid, item_id)  # 0 when absent
total = await bot.inventory.total(uid)  # all items
~~~~


3. Consume
----------

~~~~ python
await bot.inventory.remove(uid, item_id, amount=1)
~~~~

`remove` is a negative delta; stacks are pruned at zero, and `remove` never
errors on a short balance — **validate affordability yourself** before you
call it.


4. Item-owned consume
---------------------

`remove` only moves the count. To attach an effect (e.g. granting exp),
define the `consume` behavior on the `Item` definition itself — see
`plugins/frogs/items.py`, where consuming a frog grants seasonal exp *and*
emits a `FrogConsumedEvent`:

~~~~ python
await item.consume(bot, uid, self.amount)
await bot.inventory.remove(uid, item_id, self.amount)
~~~~

Run `plugin reload <name>` after changing definitions; the definitions layer
is re-registered on load.


5. Rules
--------

 -  `add`/`remove`/`modify` are available on `bot.inventory` (bound to the
    bot's db) or as module functions taking `db: Database`.
 -  Use the generic inventory for stackable member holdings — don't build a
    per-feature table for these shapes.
 -  Consume validation (`can you afford this`) stays with the caller.
