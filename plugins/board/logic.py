"""Board plugin — pure logic: filtering, hashing, scraping, stitching.

Week math lives in ``cazzubot.utils`` (the board week runs Sunday 00:00
UTC → next Sunday 00:00 UTC). No discord imports here — see
``tests/core/test_csr_boundary.py``. The framework-adjacent pieces
(message history walk, image downloads) are injected: ``scrape_week``
takes the REST client and ``build_grid`` takes a downloader, so both stay
unit-testable with fakes.
"""

import hashlib
import io
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pendulum
from PIL import Image

from cazzubot.db import Database

from .db import BoardRow, add_image, delete_image, has_sha_in_week
from .stitcher import ImageGridStitcher

MAX_IMAGES = 50  # grid cells (matches the poll plugin's item cap)
CONTENT_LIMIT = 2000  # Discord message content limit


@dataclass(slots=True)
class ScrapeResult:
    """Outcome of one scrape: new rows plus the skip reasons (for the
    command's report window)."""

    scraped: int = 0
    skipped_animated: int = 0
    skipped_duplicates: int = 0


@dataclass(slots=True)
class GridResult:
    """A stitched grid: post content (header + numbered message links),
    the grid bytes, the surviving rows, and how many rows were pruned."""

    content: str
    data: bytes
    survivors: list[BoardRow]
    pruned: int


def build_post_content(
    header: str, msg_urls: list[str], limit: int = CONTENT_LIMIT
) -> str:
    """Header + numbered message links, links on their own line.

    Links are dropped from the tail when they'd overflow the content
    limit; the ``…`` marker is only appended when it still fits, so the
    result never exceeds ``limit``.
    """
    parts = [header]
    remaining = limit - len(header) - 1
    links: list[str] = []
    for i, url in enumerate(msg_urls, 1):
        link = f"[{i}]({url})"
        if remaining < len(link) + 1:
            break
        links.append(link)
        remaining -= len(link) + 1
    parts.append(" ".join(links))
    content = "\n".join(parts)
    if len(msg_urls) > len(links) and len(content) + len(" …") <= limit:
        content += " …"
    return content


async def scrape_week(
    rest: Any,
    db: Database,
    guild_id: int,
    channel_id: int,
    start: pendulum.DateTime,
    end: pendulum.DateTime,
    *,
    download: Callable[[str], Awaitable[bytes]],
) -> ScrapeResult:
    """Walk a channel's history for the half-open [start, end) window and
    record every valid (static, within-week-unique) image as a ``board``
    row; returns the new-row count plus skip reasons for reporting.
    """
    candidates: list[tuple[Any, Any]] = []
    messages = rest.fetch_messages(channel_id, after=start)
    async for message in messages:
        if not in_week(message.created_at, start, end):
            continue
        for attachment in message.attachments:
            if is_image_attachment(attachment.media_type):
                candidates.append((message, attachment))
    # chronological order → stable row order across re-scrapes
    candidates.sort(key=lambda m_a: (m_a[0].created_at, m_a[0].id))

    start_iso, end_iso = start.isoformat(), end.isoformat()
    result = ScrapeResult()
    for message, attachment in candidates:
        data = await download(str(attachment.url))
        if is_animated(data):
            result.skipped_animated += 1
            continue
        sha = content_sha256(data)
        if await has_sha_in_week(db, sha, start_iso, end_iso):
            result.skipped_duplicates += 1
            continue
        ts = pendulum.instance(message.created_at).isoformat()
        msg_url = (
            f"https://discord.com/channels/{guild_id}/{channel_id}/"
            f"{message.id}"
        )
        if await add_image(db, ts, str(attachment.url), msg_url, sha):
            result.scraped += 1
    return result


async def build_grid(
    db: Database,
    rows: list[BoardRow],
    *,
    download: Callable[[str], Awaitable[bytes]],
    day: str,
    columns: int = 9,
    cell_size: int = 768,
) -> GridResult:
    """Download the week's images fresh, prune dead rows, stitch a grid.

    Rows whose image no longer downloads are deleted (the message was
    deleted — don't call again). When nothing survives the result is
    empty and no stitch happens; the caller decides how to report it.
    """
    paths: list[Path] = []
    survivors: list[BoardRow] = []
    pruned = 0
    with tempfile.TemporaryDirectory() as tmp:
        for row in rows:
            try:
                data = await download(row.image_url)
            except Exception:
                # the message is gone — drop the row, no more calls
                await delete_image(db, row.id)
                pruned += 1
                continue
            path = Path(tmp) / f"{row.id}.img"
            path.write_bytes(data)
            paths.append(path)
            survivors.append(row)
        if not survivors:
            return GridResult(
                content="", data=b"", survivors=[], pruned=pruned
            )

        out = Path(tmp) / "grid.webp"
        ImageGridStitcher().stitch(
            [str(p) for p in paths],
            str(out),
            images_per_row=columns,
            target_size=(cell_size, cell_size),
        )
        data = out.read_bytes()

    # plain content so the text renders above the attachment; links on
    # their own line, tail-dropped when over the content limit
    header = (
        f"Week {day} — {len(survivors)} image(s) · "
        f"{columns} cols · {cell_size}px"
    )
    content = build_post_content(header, [row.msg_url for row in survivors])
    return GridResult(
        content=content, data=data, survivors=survivors, pruned=pruned
    )


def in_week(
    created_at: datetime, start: pendulum.DateTime, end: pendulum.DateTime
) -> bool:
    """True when a message timestamp falls inside the scrape window."""
    return start <= created_at < end


def is_image_attachment(media_type: str | None) -> bool:
    """v1 rule: attachments whose content type starts with ``image/``.

    Formats like GIF/WebP/APNG may be static *or* animated — the final
    static-only decision happens on the bytes (see ``is_animated``).
    """
    return bool(media_type and media_type.startswith("image/"))


def is_animated(data: bytes) -> bool:
    """True when the image has more than one frame.

    The grid is static-only: animated GIF/WebP/APNG uploads are skipped at
    scrape time. Unreadable bytes count as static (they surface later as
    dead rows when the grid is posted).
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            # n_frames is set at runtime by ImageFile, missing from stubs
            return image.n_frames > 1  # pyright: ignore[reportAttributeAccessIssue]
    except Exception:
        return False


def content_sha256(data: bytes) -> str:
    """Hex digest used for within-week dedup."""
    return hashlib.sha256(data).hexdigest()
