"""Board plugin package — weekly image scrape → numbered grid.

Core flow: ``/board scrape`` collects a week's image attachments (hash
dedup), ``/board post`` stitches them into a numbered grid and posts it in
the invoking channel. The weekly automation (scheduler tag
``board_weekly``, Sunday 00:00 UTC) scrapes the source channel, registers
+ opens a vote poll for the grid, and posts poll + grid + ``MESSAGE_OPEN``
(see ``plugins/board/weekly.py``); ``/board weekly`` runs the same flow
manually for testing.
"""

import logging

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from cazzubot.scheduler import At
from typing_extensions import override

from . import db
from .weekly import on_board_weekly_close, run_weekly

_log = logging.getLogger(__name__)

# Sunday 00:00 UTC — re-armed by on_board_weekly_due and on_load
CADENCE = At(weekday=(6,), time="00:00")


async def on_board_weekly_due(
    bot: CazzuBot, _payload: dict[str, object]
) -> None:
    """Scheduler handler for tag ``board_weekly`` — run, then re-arm.

    Every fire is a legitimate run: on-schedule, late (bot was down over
    Sunday), or a retry of a failed attempt. Re-arming last keeps the
    fired row live while the flow runs, so the scheduler's retry policy
    can bump it if the run raises.
    """
    result = await run_weekly(bot)
    _log.info(
        "board_weekly fire: week=%s aborted=%s scraped=%d poll=%s",
        result.week_label,
        result.aborted,
        result.scraped,
        result.poll_id,
    )
    await bot.scheduler.arm("board_weekly", CADENCE)


class BoardPlugin(Plugin):
    """Board plugin — weekly image scrape → numbered grid."""

    name = "board"
    schema = db.SCHEMA
    extensions = ["plugins.board.extension"]
    scheduled = {
        "board_weekly": on_board_weekly_due,
        "board_weekly_close": on_board_weekly_close,
    }
    # the weekly flow registers polls and sends the poll message, and
    # renders the banner via plugins.misc.logic — both must be loaded
    depends_on = ("poll", "misc")

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Arm the Sunday cadence — never clobber an existing row."""
        await bot.scheduler.arm_if_rowless("board_weekly", CADENCE)


plugin = BoardPlugin()
