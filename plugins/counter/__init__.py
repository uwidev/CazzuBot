"""Counter plugin package."""

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from typing_extensions import override

from . import db
from .cog import CounterCog, CounterView, on_counter_expire


class CounterPlugin(Plugin):
    name = "counter"
    schema = db.SCHEMA
    cogs = [CounterCog]
    scheduled = {"counter": on_counter_expire}

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Re-attach the persistent button to every existing counter."""
        for mid in await db.all_mids(bot.db):
            bot.add_view(CounterView(bot), message_id=mid)


plugin = CounterPlugin()
