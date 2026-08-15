"""Frogs plugin package."""

import logging

import pendulum

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from cazzubot.scheduler import At
from typing_extensions import override

from . import db, factory, species as species
from .assets import FrogAsset

_log = logging.getLogger(__name__)

# the season rollover: first instant of Jan/Apr/Jul/Oct — freezes every
# normal stack into frozen (the quarterly soft reset)
QUARTERLY_CADENCE = At(day=1, months=(1, 4, 7, 10), time="00:00")
# the frog half of the midnight reset: lifetime captures resync from the
# logs (the exp half lives in the experience plugin under tag ``daily``)
DAILY_CADENCE = At(time="00:00")

DAILY_FROG_TAG = "daily.frog"
QUARTERLY_TAG = "quarterly"


async def on_daily_frog_due(
    bot: CazzuBot, _payload: dict[str, object]
) -> None:
    """Scheduler handler for tag ``daily.frog`` — resync captures, re-arm.

    The two halves of the midnight reset run as independent rows on the
    same cadence (this one in frogs, ``daily`` in experience), so each
    keeps its own retry semantics.
    """
    await db.sync_with_frog_logs(bot.db)
    await _rearm(bot, DAILY_FROG_TAG, DAILY_CADENCE)


async def on_quarterly_due(
    bot: CazzuBot, _payload: dict[str, object]
) -> None:
    """Scheduler handler for tag ``quarterly`` — freeze, then re-arm.

    Every fire is a season rollover by construction, so the freeze is
    unconditional (and idempotent). Re-arming last keeps the fired row
    live while the freeze runs, so a failed freeze is retried.
    """
    await db.freeze_frogs(bot.db)
    await _rearm(bot, QUARTERLY_TAG, QUARTERLY_CADENCE)


async def _rearm(bot: CazzuBot, tag: str, cadence: At) -> None:
    """Drop the tag's stale rows and schedule the next occurrence."""
    await bot.scheduler.drop_tag(tag)
    await bot.scheduler.add(
        tag, cadence.next_run(pendulum.now("UTC")), {"retry": True}
    )


async def _arm_if_rowless(bot: CazzuBot, tag: str, cadence: At) -> None:
    """Arm a cadence on load — but never clobber an existing row.

    A row left from a previous run is either future (already armed) or
    overdue (bot was down over the boundary — the scheduler fires it on
    boot and the work runs then). Only a rowless install needs a fresh
    arm.
    """
    if not await bot.scheduler.get(tag):
        await _rearm(bot, tag, cadence)


class FrogsPlugin(Plugin):
    name = "frogs"
    schema = db.SCHEMA
    extensions = ["plugins.frogs.extension"]
    scheduled = {
        "frog": factory.on_frog_due,
        DAILY_FROG_TAG: on_daily_frog_due,
        QUARTERLY_TAG: on_quarterly_due,
    }
    # consuming frogs grants exp via the experience tables
    depends_on = ("experience",)
    asset_decl = FrogAsset

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        # queue spawn tasks for any channels configured in a previous run
        await factory.reset_frog_tasks(bot)
        # clean up frog messages left dangling by a previous process
        await factory.cleanup_dangling_frogs(bot)
        # arm the cadences this plugin owns (capture resync, season freeze)
        await _arm_if_rowless(bot, DAILY_FROG_TAG, DAILY_CADENCE)
        await _arm_if_rowless(bot, QUARTERLY_TAG, QUARTERLY_CADENCE)


plugin = FrogsPlugin()
