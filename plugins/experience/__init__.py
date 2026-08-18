"""Experience plugin package."""

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from cazzubot.scheduler import At
from typing_extensions import override

from . import db

# the exp half of the midnight reset: msg counts back to 1, cooldowns
# cleared, lifetime resynced from the logs (the frog half — capture
# resync — lives in the frogs plugin under its own tag ``daily.frog``)
CADENCE = At(time="00:00")

DAILY_TAG = "daily"


async def on_daily_due(bot: CazzuBot, _payload: dict[str, object]) -> None:
    """Scheduler handler for tag ``daily`` — reset, then re-arm.

    Every fire is a legitimate reset: on-schedule, late (bot was down at
    midnight), or a retry of a failed attempt. Re-arming last keeps the
    fired row live while the reset runs, so the scheduler's retry policy
    can bump it if the reset fails.
    """
    await db.reset_all_msg_cnt(bot.db)
    await db.reset_all_cdr(bot.db)
    await db.sync_with_exp_logs(bot.db)
    await bot.scheduler.arm(DAILY_TAG, CADENCE)


class ExperiencePlugin(Plugin):
    """Experience plugin — message exp pipeline and membership card."""

    name = "experience"
    schema = db.SCHEMA
    extensions = ["plugins.experience.extension"]
    scheduled = {DAILY_TAG: on_daily_due}
    # every awarded message presents level-ups and rank-ups, and exp top
    # queries rank roles — levels and ranks must be loaded with this
    depends_on = ("levels", "ranks")

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Arm the midnight cadence — never clobber an existing row."""
        await bot.scheduler.arm_if_rowless(DAILY_TAG, CADENCE)


plugin = ExperiencePlugin()
