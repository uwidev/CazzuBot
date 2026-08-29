"""CazzuBot v2 — plugin-based Discord bot for Club Cirno.

Core package. Plugins live in ``plugins/``; see docs/ARCHITECTURE.md.
"""

from cazzubot.assets import AssetKind, AssetSpec, Assets
from cazzubot.bot import CazzuBot
from cazzubot.config import Config
from cazzubot.db import Database
from cazzubot.effects import Effects
from cazzubot.inventory import Inventory
from cazzubot.items import Item, Items
from cazzubot.lifecycle import Lifecycle
from cazzubot.plugin import Plugin
from cazzubot.scheduler import Scheduler
from cazzubot.settings import Settings

__all__ = [
    "AssetKind",
    "AssetSpec",
    "Assets",
    "CazzuBot",
    "Config",
    "Database",
    "Effects",
    "Inventory",
    "Item",
    "Items",
    "Lifecycle",
    "Plugin",
    "Scheduler",
    "Settings",
]
