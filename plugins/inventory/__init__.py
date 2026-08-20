"""Inventory plugin — the generic /inventory view + consume commands.

The generic inventory store (``cazzubot/inventory.py``) counts every
"player × item × stack" (frog species×state today, badges/shop later);
this plugin surfaces it as two user-facing commands. It declares no schema
and no assets — the store is core — so the plugin is just the commands plus
the walk over ``bot.inventory.rows_indexed``. What an item *is* (its icon
for the grid, its consume behavior) comes from the item-definitions registry
``bot.items``, keyed by the immutable ``item_id`` oracle.
"""

from cazzubot import Plugin


class InventoryPlugin(Plugin):
    """Inventory plugin — view and consume a member's holdings."""

    name = "inventory"
    extensions = ["plugins.inventory.extension"]


plugin = InventoryPlugin()
