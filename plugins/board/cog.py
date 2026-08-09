"""Board plugin extension — scrape a week's images, post a numbered grid.

Core board flow (v1's ``board scrape`` plus the stitching half that was
TODO in v1): ``/board scrape`` walks a week's message history and records
each valid (static, within-week-unique) image as a ``board`` row —
timestamp, CDN attachment url, message link, content hash. ``/board post``
downloads the most recent week's rows fresh (rows whose image no longer
downloads are pruned — the message was deleted), stitches them into a
numbered grid, and posts the grid with per-image message links in the
message content (text renders above the attachment). The weekly
automation (scheduled cadence, poll tie-in, winner banner) is backlogged.
"""

import logging
import tempfile
from pathlib import Path
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
from .logic import (
    MAX_IMAGES,
    build_post_content,
    content_sha256,
    in_week,
    is_animated,
    is_image_attachment,
)
from .stitcher import ImageGridStitcher

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

_OWNER = prefab_checks.owner_only


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


async def _download_url(url: str) -> bytes:
    """Fetch raw bytes from a URL (module-level for test stubbing)."""
    return await hikari.files.URL(url).read()


async def _download(attachment: hikari.Attachment) -> bytes:
    """Fetch an attachment's bytes."""
    return await _download_url(str(attachment.url))


board = lightbulb.Group("board", "Weekly image board.")


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
        day = start.format("YYYY-MM-DD")
        week_year, week_no = start.isocalendar()[0], start.isocalendar()[1]
        cid = (
            self.channel.id if self.channel is not None else ctx.channel_id
        )
        guild_id = bot.config.guild_id

        async with command_window(ctx) as window:
            window.info(
                f"Scraping <#{cid}> for {week_year}-W{week_no:02} "
                f"({day})..."
            )
            await window.flush()  # ack before the long history walk

            candidates: list[tuple[hikari.Message, hikari.Attachment]] = []
            messages = bot.rest.fetch_messages(cid, after=start)
            async for message in messages:
                if not in_week(message.created_at, start, end):
                    continue
                for attachment in message.attachments:
                    if is_image_attachment(attachment.media_type):
                        candidates.append((message, attachment))
            # chronological order → stable row order across re-scrapes
            candidates.sort(key=lambda m_a: (m_a[0].created_at, m_a[0].id))

            start_iso, end_iso = start.isoformat(), end.isoformat()
            scraped = 0
            skipped_animated = 0
            skipped_duplicates = 0
            for message, attachment in candidates:
                data = await _download(attachment)
                if is_animated(data):
                    skipped_animated += 1
                    continue
                sha = content_sha256(data)
                if await db.has_sha_in_week(
                    bot.db, sha, start_iso, end_iso
                ):
                    skipped_duplicates += 1
                    continue
                ts = pendulum.instance(message.created_at).isoformat()
                msg_url = (
                    f"https://discord.com/channels/{guild_id}/{cid}/"
                    f"{message.id}"
                )
                if await db.add_image(
                    bot.db, ts, str(attachment.url), msg_url, sha
                ):
                    scraped += 1

            if skipped_animated:
                window.info(
                    f"Skipped {skipped_animated} animated image(s) — "
                    "the grid is static-only."
                )
            if skipped_duplicates:
                window.info(
                    f"Skipped {skipped_duplicates} duplicate image(s) — "
                    "already scraped this week."
                )
            window.success(
                "Scraped "
                f"{scraped} new image(s) from <#{cid}> for "
                f"{week_year}-W{week_no:02} ({day})."
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
                f"Stitching {len(rows)} image(s) for week {day}..."
            )
            await window.flush()  # ack before downloads + CPU-bound stitch

            selected = rows[:MAX_IMAGES]
            if len(selected) < len(rows):
                window.warn(f"Truncated to the first {MAX_IMAGES} images.")

            paths: list[Path] = []
            survivors: list[db.BoardRow] = []
            pruned = 0
            with tempfile.TemporaryDirectory() as tmp:
                for row in selected:
                    try:
                        data = await _download_url(row.image_url)
                    except Exception:
                        # the message is gone — drop the row, no more calls
                        await db.delete_image(bot.db, row.id)
                        pruned += 1
                        continue
                    path = Path(tmp) / f"{row.id}.img"
                    path.write_bytes(data)
                    paths.append(path)
                    survivors.append(row)
                if pruned:
                    window.warn(
                        f"Deleted {pruned} row(s) — image no longer "
                        "downloads (message deleted)."
                    )
                if not paths:
                    window.error(
                        "No images left — their messages are gone. "
                        "Re-run /board scrape."
                    )
                    return

                out = Path(tmp) / "grid.webp"
                try:
                    ImageGridStitcher().stitch(
                        [str(p) for p in paths],
                        str(out),
                        images_per_row=self.columns,
                        target_size=(self.cell_size, self.cell_size),
                    )
                except UserInputError as err:
                    window.error(str(err))
                    return
                data = out.read_bytes()

            # plain content so the text renders above the attachment;
            # links on their own line, tail-dropped when over the limit
            header = (
                f"Week {day} — {len(paths)} image(s) · "
                f"{self.columns} cols · {self.cell_size}px"
            )
            content = build_post_content(
                header, [row.msg_url for row in survivors]
            )
            await ctx.respond(
                content=content,
                attachment=hikari.Bytes(data, f"board-{day}.webp"),
            )


loader.command(board)
