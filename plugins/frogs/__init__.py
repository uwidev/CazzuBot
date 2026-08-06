"""Frogs plugin package."""

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from typing_extensions import override

from . import db, factory
from .cog import FrogsCog


class FrogsPlugin(Plugin):
    name = "frogs"
    schema = db.SCHEMA
    cogs = [FrogsCog]
    scheduled = {"frog": factory.on_frog_due}

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        # queue spawn tasks for any channels configured in a previous run
        await factory.reset_frog_tasks(bot)


plugin = FrogsPlugin()
