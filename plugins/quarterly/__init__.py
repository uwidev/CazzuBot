"""Quarterly plugin — freezes frogs when the season rolls over.

Port of v1's ``ext/quarterly.py``. Runs its check daily at 00:00 UTC; when the
quarter index increases, all normal frogs become frozen frogs.
"""

import datetime
import logging

import pendulum
from discord.ext import commands, tasks

from cazzubot import Plugin, utils
from cazzubot.bot import CazzuBot
from cazzubot.timeparse import parse_iso8601
from typing_extensions import override

from plugins.frogs import db as frog_db

_log = logging.getLogger(__name__)

CHECK_TIME = datetime.time(0, tzinfo=datetime.timezone.utc)
LAST_KEY = "quarterly.last_quarterly"


class QuarterlyCog(commands.Cog):
    """Quarterly frog-freeze resets."""

    def __init__(
        self, bot: CazzuBot, *, force_reset: bool = False
    ) -> None:
        self.bot = bot
        self.force_reset = force_reset
        self.quarterly_reset.start()

    @tasks.loop(time=CHECK_TIME)
    async def quarterly_reset(self) -> None:
        last_raw = await self.bot.settings.get(LAST_KEY)
        now = pendulum.now("UTC")
        if last_raw:
            last = parse_iso8601(last_raw)
            last_quarter = (last.year, utils.month2season(last.month))
        else:
            last_quarter = (-1, -1)
        this_quarter = (now.year, utils.month2season(now.month))
        if this_quarter > last_quarter:
            await self.reset()

    async def reset(self) -> None:
        _log.info("Running quarterly reset — freezing frogs")
        await frog_db.freeze_frogs(self.bot.db)
        await self.bot.settings.set(LAST_KEY, pendulum.now("UTC"))

    @override
    async def cog_load(self) -> None:
        if self.force_reset:
            await self.reset()
            self.force_reset = False

    @override
    async def cog_unload(self) -> None:
        self.quarterly_reset.cancel()


class QuarterlyPlugin(Plugin):
    name = "quarterly"
    cogs = [QuarterlyCog]

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Freeze frogs if the quarter rolled over while the bot was down."""
        last_raw = await bot.settings.get(LAST_KEY)
        force = False
        if last_raw is None:
            _log.warning(
                "no record of the last quarterly reset; forcing one"
            )
            force = True
        elif (
            pendulum.now("UTC").year,
            utils.month2season(pendulum.now("UTC").month),
        ) > (
            parse_iso8601(last_raw).year,
            utils.month2season(parse_iso8601(last_raw).month),
        ):
            force = True

        if force:
            cog = bot.get_cog("QuarterlyCog")
            if isinstance(cog, QuarterlyCog):
                await cog.reset()


plugin = QuarterlyPlugin()
