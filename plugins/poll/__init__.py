"""Poll plugin package."""

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from typing_extensions import override

from . import db
from .cog import PollCog, PollView


class PollPlugin(Plugin):
    name = "poll"
    schema = db.SCHEMA
    cogs = [PollCog]

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Re-attach the vote button to every existing poll message."""
        rows = await bot.db.fetch_models(
            db.PollRow, "SELECT id, mid FROM poll WHERE mid IS NOT NULL"
        )
        for row in rows:
            assert row.mid is not None  # WHERE mid IS NOT NULL
            bot.add_view(PollView(bot, row.id), message_id=row.mid)


plugin = PollPlugin()
