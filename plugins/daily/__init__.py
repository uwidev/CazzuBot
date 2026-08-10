"""Daily plugin — resets message counts and cooldowns at 00:00 UTC.

The midnight cadence is armed through the central scheduler (tag
``daily``); every fire runs the reset and re-arms the next midnight. The
task row is the sole schedule: an overdue row (bot was down at midnight)
fires on boot so a missed reset runs late instead of being skipped, and a
failed reset is retried by the scheduler's retry policy.
"""

import logging

import pendulum

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from cazzubot.scheduler import At
from typing_extensions import override

from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db

_log = logging.getLogger(__name__)

# once a day at 00:00 UTC — re-armed by on_daily_due and on_load
CADENCE = At(time="00:00")


async def reset(bot: CazzuBot) -> None:
    """Daily reset: msg counts back to 1, cooldowns cleared, resync."""
    _log.info("Running daily reset")
    await exp_db.reset_all_msg_cnt(bot.db)
    await exp_db.reset_all_cdr(bot.db)
    await exp_db.sync_with_exp_logs(bot.db)
    await frog_db.sync_with_frog_logs(bot.db)


async def on_daily_due(bot: CazzuBot, _payload: dict[str, object]) -> None:
    """Scheduler handler for tag ``daily`` — reset, then re-arm.

    Every fire is a legitimate reset: on-schedule, late (bot was down at
    midnight), or a retry of a failed attempt. Re-arming last keeps the
    fired row live while the reset runs, so the scheduler's retry policy
    can bump it if the reset fails.
    """
    await reset(bot)
    # re-arm: drop stale rows, schedule the next midnight
    await bot.scheduler.drop_tag("daily")
    await bot.scheduler.add(
        "daily", CADENCE.next_run(pendulum.now("UTC")), {"retry": True}
    )


class DailyPlugin(Plugin):
    name = "daily"
    scheduled = {"daily": on_daily_due}
    # resets message counts and cooldowns owned by experience and frogs
    depends_on = ("experience", "frogs")

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Arm the midnight cadence — but never clobber an existing row.

        A row left from a previous run is either future (already armed)
        or overdue (bot was down at midnight — the scheduler fires it on
        boot and the reset runs then). Only a rowless install needs a
        fresh arm.
        """
        if not await bot.scheduler.get("daily"):
            await bot.scheduler.drop_tag("daily")
            await bot.scheduler.add(
                "daily",
                CADENCE.next_run(pendulum.now("UTC")),
                {"retry": True},
            )


plugin = DailyPlugin()
