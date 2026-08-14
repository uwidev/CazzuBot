"""CazzuBot v2 — plugin-based Discord bot for Club Cirno.

Core package. Plugins live in ``plugins/``; see docs/ARCHITECTURE.md.
"""

from cazzubot.assets import AssetKind, AssetSpec, Assets
from cazzubot.bot import CazzuBot
from cazzubot.config import Config
from cazzubot.db import Database
from cazzubot.inventory import Inventory
from cazzubot.lifecycle import Lifecycle
from cazzubot.member_effects import MemberEffects
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
    "Inventory",
    "Lifecycle",
    "MemberEffects",
    "Plugin",
    "Scheduler",
    "Settings",
]
