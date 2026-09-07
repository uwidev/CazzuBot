"""CazzuBot v2 — plugin-based Discord bot for Club Cirno.

Core package. Plugins live in ``plugins/``; see docs/ARCHITECTURE.md.
"""

from core.assets import AssetKind, AssetSpec, Assets
from core.bot import CazzuBot
from core.config import Config
from core.db import Database
from core.statuses import Statuses
from core.inventory import Inventory
from core.items import Item, Items
from core.lifecycle import Lifecycle
from core.plugin import Plugin
from core.scheduler import Scheduler
from core.settings import Settings

__all__ = [
    "AssetKind",
    "AssetSpec",
    "Assets",
    "CazzuBot",
    "Config",
    "Database",
    "Statuses",
    "Inventory",
    "Item",
    "Items",
    "Lifecycle",
    "Plugin",
    "Scheduler",
    "Settings",
]
