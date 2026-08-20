"""Inventory plugin — the generic /inventory grid over the shared ledger.

The generic inventory store (``cazzubot/inventory.py``) counts every
"player × item × stack" (frog species×state today, badges/shop later);
this plugin surfaces it as one user-facing view. It declares no schema and
no assets — the store is core — so the plugin is just the command plus the
walk over ``bot.inventory.rows_indexed``. Namespace rendering (species →
name + emoji) is delegated to each plugin's renderer via the registry on
``bot.inventory``.
"""

from cazzubot import Plugin


class InventoryPlugin(Plugin):
    """Inventory plugin — view a member's holdings across all namespaces."""

    name = "inventory"
    extensions = ["plugins.inventory.extension"]


plugin = InventoryPlugin()
