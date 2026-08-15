"""Board plugin extension — scrape a week's images, post a numbered grid.

Core board flow (v1's ``board scrape`` plus the stitching half that was
TODO in v1): ``/board scrape`` walks a week's message history and records
each valid (static, within-week-unique) image as a ``board`` row —
timestamp, CDN attachment url, message link, content hash. ``/board post``
downloads the most recent week's rows fresh (rows whose image no longer
downloads are pruned — the message was deleted), stitches them into a
numbered grid, and posts the grid with per-image message links in the
message content (text renders above the attachment). The weekly
automation (``board_weekly`` scheduler tag, see ``weekly.py``) runs the
scrape → poll → grid flow every Sunday 00:00 UTC; ``/board weekly``
triggers it manually for testing. The winner banner is still backlogged.
"""

import logging
from typing import cast

import hikari
import lightbulb
import pendulum
from lightbulb.prefab import checks as prefab_checks

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.window import command_window, window_error

from . import db
from .logic import MAX_IMAGES, build_grid, scrape_week
from .weekly import run_weekly

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

_OWNER = prefab_checks.owner_only


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


async def _download_url(url: str) -> bytes:
    """Fetch raw bytes from a URL (module-level for test stubbing)."""
    return await hikari.files.URL(url).read()


board = lightbulb.Group(
    "board",
    "Weekly image board.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


@board.register
class Scrape(
    lightbulb.SlashCommand,
    name="scrape",
    description="Scrape this week's image attachments from a channel.",
    hooks=[_OWNER],
):
    channel = lightbulb.channel(
        "channel",
        "Channel to scrape (default: this one)",
        default=None,
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )
    week = lightbulb.integer(
        "week",
        "Week of the year to scrape (default: last week)",
        default=None,
        min_value=1,
        max_value=53,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        now = pendulum.now("UTC")
        if self.week is None:
            start = utils.week_start(now).subtract(days=7)  # last week
        else:
            start = utils.week_start_of(now.year, self.week)
        end = start.add(days=7)
        week_no = start.isocalendar()[1]
        cid = (
            self.channel.id if self.channel is not None else ctx.channel_id
        )
        guild_id = bot.config.guild_id

        async with command_window(ctx) as window:
            window.info(f"Scraping <#{cid}> for week {week_no}...")
            await window.flush()  # ack before the long history walk

            result = await scrape_week(
                bot.rest,
                bot.db,
                guild_id,
                cid,
                start,
                end,
                download=_download_url,
            )
            if result.skipped_animated:
                window.info(
                    f"Skipped {result.skipped_animated} animated image(s) — "
                    "the grid is static-only."
                )
            if result.skipped_duplicates:
                window.info(
                    f"Skipped {result.skipped_duplicates} duplicate "
                    "image(s) — already scraped this week."
                )
            window.success(
                "Scraped "
                f"{result.scraped} new image(s) from <#{cid}> for "
                f"week {week_no}."
            )


@board.register
class Post(
    lightbulb.SlashCommand,
    name="post",
    description="Stitch the scraped week into a numbered grid and post it.",
    hooks=[_OWNER],
):
    columns = lightbulb.integer(
        "columns",
        "Images per row (default 9)",
        default=9,
        min_value=1,
        max_value=20,
    )
    cell_size = lightbulb.integer(
        "cell_size",
        "Square cell size in px (default 768)",
        default=768,
        min_value=64,
        max_value=1024,
    )
    week = lightbulb.integer(
        "week",
        "Week of the year to post (default: most recent scraped)",
        default=None,
        min_value=1,
        max_value=53,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        now = pendulum.now("UTC")
        if self.week is None:
            latest = await db.latest_ts(bot.db)
            if latest is None:
                await window_error(
                    ctx, "Nothing scraped yet — run /board scrape first."
                )
                return
            latest_dt = pendulum.parse(latest)
            if not isinstance(latest_dt, pendulum.DateTime):
                raise UserInputError("invalid timestamp in board table")
            week_no, year = utils.week_number(latest_dt)
        else:
            week_no, year = self.week, now.year
        start = utils.week_start_of(year, week_no)
        end = start.add(days=7)
        day = start.format("YYYY-MM-DD")

        async with command_window(ctx) as window:
            rows = await db.get_week_images(
                bot.db, start.isoformat(), end.isoformat()
            )
            window.info(
                f"Stitching {len(rows)} image(s) for week {week_no}..."
            )
            await window.flush()  # ack before downloads + CPU-bound stitch

            selected = rows[:MAX_IMAGES]
            if len(selected) < len(rows):
                window.warn(f"Truncated to the first {MAX_IMAGES} images.")

            try:
                grid = await build_grid(
                    bot.db,
                    selected,
                    download=_download_url,
                    week=week_no,
                    columns=self.columns,
                    cell_size=self.cell_size,
                )
            except UserInputError as err:
                window.error(str(err))
                return
            if grid.pruned:
                window.warn(
                    f"Deleted {grid.pruned} row(s) — image no longer "
                    "downloads (message deleted)."
                )
            if not grid.survivors:
                window.error(
                    "No images left — their messages are gone. "
                    "Re-run /board scrape."
                )
                return

            # plain content so the text renders above the attachment
            await ctx.respond(
                content=grid.content,
                attachment=hikari.Bytes(grid.data, f"board-{day}.webp"),
            )


@board.register
class Weekly(
    lightbulb.SlashCommand,
    name="weekly",
    description="Run the weekly board scrape + poll flow now (testing).",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        async with command_window(ctx) as window:
            window.info("Running weekly board flow...")
            await window.flush()  # ack before the long scrape
            result = await run_weekly(bot, force=True)
            if result.aborted:
                window.error(result.reason)
                return
            window.success(
                f"Weekly board done: {result.week_label} · "
                f"{result.scraped} image(s) · poll ID#{result.poll_id}"
            )


loader.command(board)
