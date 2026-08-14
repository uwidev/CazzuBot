"""Frogs plugin package."""

from typing_extensions import override

from cazzubot import Plugin
from cazzubot.bot import CazzuBot

from . import db, factory, species as species
from .assets import FrogAsset


class FrogsPlugin(Plugin):
    name = "frogs"
    schema = db.SCHEMA
    extensions = ["plugins.frogs.cog"]
    scheduled = {"frog": factory.on_frog_due}
    # consuming frogs grants exp via the experience tables
    depends_on = ("experience",)
    asset_decl = FrogAsset

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        # queue spawn tasks for any channels configured in a previous run
        await factory.reset_frog_tasks(bot)
        # clean up frog messages left dangling by a previous process
        await factory.cleanup_dangling_frogs(bot)


plugin = FrogsPlugin()
