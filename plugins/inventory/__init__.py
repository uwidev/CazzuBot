"""Inventory plugin — the generic /inventory view + consume commands.

The generic inventory store (``core/inventory.py``) counts every
"player × item × stack" (frog species×state today, badges/shop later);
this plugin surfaces it as two user-facing commands plus one table of its
own — ``member_item_log`` (``db.py``), the append-only history of consume
actions. The store stays core; the *history* is this plugin's concern, so
the plugin owns that schema and nothing else. What an item *is* (its icon
for the view, its consume behavior) comes from the item-definitions registry
``bot.items``, keyed by the immutable ``item_id`` oracle.
"""

from core import Plugin

from . import db


class InventoryPlugin(Plugin):
    """Inventory plugin — view and consume a member's holdings."""

    name = "inventory"
    schema = db.SCHEMA
    extensions = ["plugins.inventory.extension"]

    # footer tips owned by this plugin (context -> strings); registered with
    # bot.tips at load, so the /inventory view/info footers draw from it
    tip_sets = {
        "item": (
            "Check what an item does with /inventory info <slot>!",
            "Use an item with /inventory consume <slot> [amount]!",
            "Thaw a frozen item with /inventory thaw <slot> [amount]!",
        ),
    }


plugin = InventoryPlugin()
