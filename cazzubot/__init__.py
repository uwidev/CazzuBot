"""CazzuBot v2 — plugin-based Discord bot for Club Cirno.

Core package. Plugins live in ``plugins/``; see docs/ARCHITECTURE.md.
"""

from cazzubot.bot import CazzuBot
from cazzubot.config import Config
from cazzubot.db import Database
from cazzubot.plugin import Plugin
from cazzubot.scheduler import Scheduler
from cazzubot.settings import Settings

__all__ = [
	"CazzuBot",
	"Config",
	"Database",
	"Plugin",
	"Scheduler",
	"Settings",
]
