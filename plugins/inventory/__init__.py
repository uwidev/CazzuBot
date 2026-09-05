"""Inventory plugin — the generic /inventory view + consume commands.

The generic inventory store (``cazzubot/inventory.py``) counts every
"player × item × stack" (frog species×state today, badges/shop later);
this plugin surfaces it as two user-facing commands. It declares no schema
and no assets — the store is core — so the plugin is just the commands plus
the compacted slot walk (`_indexed_resolved` in the extension: only ids
that still resolve become slots, re-derived to be contiguous — hidden
holdings never leave a gap). What an item *is* (its icon
for the grid, its consume behavior) comes from the item-definitions registry
``bot.items``, keyed by the immutable ``item_id`` oracle.
"""

from cazzubot import Plugin


class InventoryPlugin(Plugin):
    """Inventory plugin — view and consume a member's holdings."""

    name = "inventory"
    extensions = ["plugins.inventory.extension"]


plugin = InventoryPlugin()
