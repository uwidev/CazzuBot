"""Weekly board automation — Sunday 00:00 scrape → poll → grid → open.

The ``board_weekly`` scheduler tag fires at ``At(weekday=(6,), time="00:00")``
(Sunday 00:00 UTC): scrape the just-ended week from the source channel,
register + open a vote poll (items = grid cells, ``max_vote = n // 20 + 1``),
then send ONE combined message — role-ping "voting has opened" announcement
+ numbered grid links in the content, the stitched grid as the attachment,
the poll embed + vote button as the embed/component. ``/board weekly`` runs
the same flow manually (``force=True``, bypassing the done-guard) for
testing.

Targets are selected by ``bot.config.guild_kind`` (loaded from
``GUILD_ID_PROD``/``GUILD_ID_DEV`` in ``.env``): production scrapes the
previous week with the production channels, development scrapes the
current week with the development channels.
"""

import logging
import random
from dataclasses import dataclass

import hikari
import pendulum

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError

from plugins.board import db as board_db
from plugins.board.logic import MAX_IMAGES, build_grid, scrape_week
from plugins.misc.logic import prepare_banner
from plugins.poll import db as poll_db
from plugins.poll.cog import build_send_payload, set_poll_open

_log = logging.getLogger(__name__)

# -- channel ids (common noun first, variant suffix last) -----------------
SCRAPE_CHANNEL_PROD = 1002249390792122378
SCRAPE_CHANNEL_DEV = 584858037605498891
POST_CHANNEL_PROD = 327160579624009729
POST_CHANNEL_DEV = 460208165070307328

# poll copy + the voting-opened announcement (role ping + week header)
POLL_TITLE = "#just-cirno Voting W{week_no}"
POLL_DESC = "Which image best represents last week?"
VOTE_ROLE_ID = 325859646512431104
MESSAGE_OPEN = (
    "<@&{role_id}> Week {week_no} of #just-cirno voting is now open!"
)

# grid geometry for the weekly board post
GRID_COLUMNS = 5
GRID_CELL_SIZE = 768

# settings key recording which week was already run (the claim guard)
DONE_KEY = "board.weekly.done"

# the Monday-00:00 close task (payload: pid, cid, start, retry)
CLOSE_TAG = "board_weekly_close"
WINNER_MSG = "# Week {week_no} of just-cirno voting — winner:\n{msg_url}"
NO_VOTES_MSG = "# Week {week_no} of just-cirno voting — no votes!"


def weekly_targets(guild_kind: str) -> tuple[int, int, bool]:
    """(scrape_channel, post_channel, current_week) for the guild side.

    production → the production channels, scraping last week (the
    ``/board scrape`` default); development → the development channels,
    scraping the current week.
    """
    if guild_kind == "production":
        return SCRAPE_CHANNEL_PROD, POST_CHANNEL_PROD, False
    return SCRAPE_CHANNEL_DEV, POST_CHANNEL_DEV, True


@dataclass(slots=True)
class WeeklyResult:
    """Outcome of one weekly run; aborted runs carry a reason."""

    aborted: bool = False
    reason: str = ""
    week_label: str = ""
    scraped: int = 0
    poll_id: int | None = None


async def _download_url(url: str) -> bytes:
    """Fetch raw bytes from a URL (module-level for test stubbing)."""
    return await hikari.files.URL(url).read()


async def run_weekly(
    bot: CazzuBot, *, force: bool = False
) -> WeeklyResult:
    """The full weekly flow: targets → guard → scrape → claim → select →
    poll → one combined message (announcement + grid + poll embed/button).

    Re-arming the scheduler cadence is the scheduler handler's job, not
    this function's. ``force=True`` bypasses the done-guard so weeks can
    be re-run (the manual ``/board weekly`` test command).
    """
    now = pendulum.now("UTC")
    scrape_channel, post_channel, current_week = weekly_targets(
        bot.config.guild_kind
    )
    start = utils.week_start(now)
    if not current_week:
        start = start.subtract(days=7)
    end = start.add(days=7)
    week_no, year = utils.week_number(start)
    week_label = f"{year}-W{week_no:02}"
    day = start.format("YYYY-MM-DD")

    if not force:
        done = await bot.settings.get(DONE_KEY, "")
        if done == week_label:
            _log.info(
                "weekly run for %s already done; skipping", week_label
            )
            return WeeklyResult(
                aborted=True,
                reason=f"{week_label} already done",
                week_label=week_label,
            )

    # the scrape is incremental (re-scrapes add nothing), so the abort
    # decision keys on whether the week HAS rows — a force re-run of an
    # already-scraped week proceeds from the stored rows
    await scrape_week(
        bot.rest,
        bot.db,
        bot.config.guild_id,
        scrape_channel,
        start,
        end,
        download=_download_url,
    )
    rows = await board_db.get_week_images(
        bot.db, start.isoformat(), end.isoformat()
    )
    if not rows:
        _log.warning(
            "weekly scrape for %s found no images; aborting", week_label
        )
        return WeeklyResult(
            aborted=True,
            reason=f"No images scraped for {week_label}",
            week_label=week_label,
        )
    # claim the week — a failure from here on must never duplicate the
    # poll/board on retry; the owner re-runs via /board weekly or by
    # clearing the key
    await bot.settings.set(DONE_KEY, week_label)

    if len(rows) > MAX_IMAGES:
        # the grid holds MAX_IMAGES cells — sample so the poll items
        # always match the grid numbers
        rows = sorted(
            random.sample(rows, MAX_IMAGES), key=lambda r: (r.ts, r.id)
        )
    n = len(rows)

    pid = await poll_db.add_poll(
        bot.db, POLL_TITLE.format(week_no=week_no), POLL_DESC, n // 20 + 1
    )
    if pid is None:
        raise RuntimeError("poll registration returned no id")
    await poll_db.add_items_dummy(bot.db, pid, n)
    await poll_db.set_open(bot.db, pid, True)

    # one combined message: the role-ping announcement + grid header/links
    # in the content, the grid as the attachment, the poll embed + vote
    # button as the embed/component
    announcement = MESSAGE_OPEN.format(
        role_id=VOTE_ROLE_ID, week_no=week_no
    )
    try:
        grid = await build_grid(
            bot.db,
            rows,
            download=_download_url,
            week=week_no,
            columns=GRID_COLUMNS,
            cell_size=GRID_CELL_SIZE,
            header_prefix=announcement + "\n",
        )
    except UserInputError as err:
        raise RuntimeError(f"grid stitch failed: {err}") from err
    if not grid.survivors:
        raise RuntimeError("all scraped images vanished before posting")

    poll_row = await poll_db.get_poll(bot.db, pid)
    if poll_row is None:
        raise RuntimeError(f"poll #{pid} missing right after registration")
    embed, row = build_send_payload(poll_row)
    poll_message = await bot.rest.create_message(
        post_channel,
        content=grid.content,
        embed=embed,
        component=row,
        attachment=hikari.Bytes(grid.data, f"board-{day}.webp"),
        # the content opens with a <@&VOTE_ROLE_ID> ping — hikari's default
        # allowed_mentions is {"parse": []} (no pings), so enable them
        user_mentions=True,
        role_mentions=True,
    )
    await poll_db.set_mid(bot.db, pid, poll_message.id, post_channel)
    # auto-close 24h after the open (Monday 00:00 UTC for a Sunday open)
    await bot.scheduler.add(
        CLOSE_TAG,
        now.add(days=1),
        {
            "pid": pid,
            "cid": post_channel,
            "start": start.isoformat(),
            "retry": True,
        },
    )

    _log.info(
        "weekly board done: %s, %d image(s), poll #%d", week_label, n, pid
    )
    return WeeklyResult(week_label=week_label, scraped=n, poll_id=pid)


async def on_board_weekly_close(
    bot: CazzuBot, payload: dict[str, object]
) -> None:
    """Scheduler handler for ``board_weekly_close`` — close the weekly
    poll (button removed) and resolve the winner: highest-voted image →
    guild banner + winner announcement in the poll channel.
    """
    pid = int(str(payload["pid"]))
    cid = int(str(payload["cid"]))
    start = pendulum.parse(str(payload["start"]))
    if not isinstance(start, pendulum.DateTime):
        raise UserInputError("invalid week start in close payload")

    err = await set_poll_open(bot, pid, open=False)
    if err:
        _log.warning("board_weekly_close: %s", err)
    await _announce_winner(bot, pid, cid, start)


async def _announce_winner(
    bot: CazzuBot, pid: int, cid: int, start: pendulum.DateTime
) -> None:
    """The highest-voted grid cell → guild banner + winner message.

    Poll items are the grid numbers in row order, so the winning iid maps
    straight onto the week's board rows. A poll with no votes just gets
    the no-votes message (no banner change).
    """
    week_no = utils.week_number(start)[0]
    results = await poll_db.get_results(bot.db, pid)
    if not results:
        _log.info("board_weekly_close: poll #%d had no votes", pid)
        await bot.rest.create_message(
            cid, content=NO_VOTES_MSG.format(week_no=week_no)
        )
        return

    rows = await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat()
    )
    index = results[0].iid - 1  # ORDER BY count DESC
    if not 0 <= index < len(rows):
        _log.warning(
            "board_weekly_close: winner iid %d out of range (%d rows)",
            results[0].iid,
            len(rows),
        )
        return
    winner = rows[index]

    try:
        data = await _download_url(winner.image_url)
        banner = prepare_banner(data)
        await bot.rest.edit_guild(
            bot.config.guild_id, banner=hikari.Bytes(banner, "banner.jpg")
        )
    except Exception:
        # a failed banner must not lose the winner announcement
        _log.exception(
            "board_weekly_close: failed to set guild banner from %s",
            winner.image_url,
        )
    await bot.rest.create_message(
        cid,
        content=WINNER_MSG.format(week_no=week_no, msg_url=winner.msg_url),
    )
