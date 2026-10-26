"""Board plugin — pure logic: filtering, hashing, scraping, stitching.

Week math lives in ``core.utils`` (the board week runs Sunday 00:00
UTC → next Sunday 00:00 UTC). No discord imports here — see
``tests/core/test_csr_boundary.py``. The framework-adjacent pieces
(message history walk, image downloads) are injected: ``scrape_week``
takes the REST client and ``build_grid`` takes a downloader, so both stay
unit-testable with fakes.

Pagination is the grid's job: ``build_post_pages`` splits the numbered
message links over as many messages as the content limit needs (nothing is
ever dropped), and ``build_grid`` splits the grid itself at ``MAX_IMAGES``
cells per image — so a week of any size posts as link page(s) followed by
one or more grid images.
"""

import hashlib
import io
import math
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pendulum
from PIL import Image

from core.db import Database

from .db import BoardRow, add_image, delete_image, has_sha_in_week
from .stitcher import ImageGridStitcher

MAX_IMAGES = 50  # grid cells per image (matches the poll plugin's cap)
CONTENT_LIMIT = 2000  # Discord message content limit
MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # Discord's non-boosted attachment cap
UPLOAD_HEADROOM = 0.98  # re-encode below the cap, not onto it


@dataclass(slots=True)
class ScrapeResult:
    """Outcome of one scrape: new rows plus the skip reasons (for the
    command's report window)."""

    scraped: int = 0
    skipped_animated: int = 0
    skipped_duplicates: int = 0


@dataclass(slots=True)
class GridPage:
    """One posted message's worth of grid: content + its image bytes."""

    content: str
    data: bytes


@dataclass(slots=True)
class GridResult:
    """A stitched week: one entry per message to send, grid LAST.

    ``pages`` is never empty when anything survived (the last entry always
    carries an image); an empty ``survivors`` means every row was pruned.
    """

    pages: list[GridPage]
    survivors: list[BoardRow]
    pruned: int


def build_post_pages(
    header: str,
    msg_urls: Sequence[str],
    *,
    limit: int = CONTENT_LIMIT,
) -> list[str]:
    """Header + numbered message links, one message per ``limit`` chars.

    Links are never dropped: the first page opens with ``header`` and every
    page repeats it (``— continued``) so it stands on its own, and pages
    split on whole links (a single link longer than the budget still gets
    its own page — the header is then sacrificed, since Discord truncates
    the MESSAGE, not the link).

    An empty ``msg_urls`` yields the bare header — the shape a stitched
    grid with no postable rows needs to stay under the limit.
    """
    if not msg_urls:
        return [header]
    blocks: list[str] = []
    current: list[str] = []
    budget = limit - _continued_len(header)
    for i, url in enumerate(msg_urls, 1):
        link = f"[{i}]({url})"
        if current and budget - len(link) - 1 < 0:
            blocks.append(" ".join(current))
            current = []
            budget = limit - _continued_len(header)
        current.append(link)
        budget -= len(link) + 1
    blocks.append(" ".join(current))
    out: list[str] = []
    for i, block in enumerate(blocks):
        head = header if i == 0 else f"{header} — continued"
        content = f"{head}\n{block}"
        if len(content) > limit:  # a lone link bigger than the budget
            content = content[:limit]
        out.append(content)
    return out


def _continued_len(header: str) -> int:
    """Worst-case opening a link page can carry (header + continuation)."""
    return len(header) + len(" — continued") + 1


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
        if await has_sha_in_week(db, sha, start_iso, end_iso, channel_id):
            result.skipped_duplicates += 1
            continue
        ts = pendulum.instance(message.created_at).isoformat()
        msg_url = (
            f"https://discord.com/channels/{guild_id}/{channel_id}/"
            f"{message.id}"
        )
        if await add_image(
            db,
            ts,
            str(attachment.url),
            msg_url,
            sha,
            channel_id,
            message.id,
        ):
            result.scraped += 1
    return result


async def build_grid(
    db: Database,
    rows: list[BoardRow],
    *,
    download: Callable[[str], Awaitable[bytes]],
    week: int,
    columns: int = 9,
    cell_size: int = 768,
    header_prefix: str = "",
    max_content: int = CONTENT_LIMIT,
    max_page_bytes: int = MAX_UPLOAD_BYTES,
) -> GridResult:
    """Download the week's images fresh, prune dead rows, stitch + paginate.

    Rows whose image no longer downloads are deleted (the message was
    deleted — don't call again) and drop out of the numbering. The grid
    holds at most ``MAX_IMAGES`` cells per image: a bigger week is split
    into several images in cell order, and the pages of numbered message
    links (never truncated) come FIRST while the grid image(s) come LAST —
    callers append nothing after them.

    ``week`` names the header ("Week N — …"); ``header_prefix`` is
    prepended to it (e.g. the weekly voting-opened announcement) and rides
    the first page only, so the weekly post opens with its role ping. Each
    image is encoded under ``max_page_bytes`` (re-encode, then downscale);
    an empty result means nothing survived the download.
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
            return GridResult(pages=[], survivors=[], pruned=pruned)

        # every numbered link, paginated across as many messages as it
        # takes — this is the "goto any grid message" index, so nothing is
        # dropped. The FIRST image rides the LAST link page (the combined
        # post users know: text, then its attachment) whenever it fits;
        # extra images follow on their own messages.
        header = f"{header_prefix}Week {week} — {len(survivors)} image(s)"
        contents = build_post_pages(
            header,
            [row.msg_url for row in survivors],
            limit=max_content,
        )

        stitcher = ImageGridStitcher()
        chunks = _chunks(len(paths), MAX_IMAGES)
        pages: list[GridPage] = []
        for chunk_no, chunk in enumerate(chunks):
            out = Path(tmp) / f"grid-{chunk_no}.webp"
            canvas = stitcher.stitch(
                [str(paths[i]) for i in chunk],
                str(out),
                images_per_row=columns,
                target_size=(cell_size, cell_size),
            )
            data = _encode_upload(canvas, max_page_bytes)
            if chunk_no == 0:
                # the index's last page carries the first grid image
                content = contents[-1]
                pages.extend(GridPage(c, b"") for c in contents[:-1])
            else:
                # a split grid labels its cell range so each image is
                # identifiable on its own
                cells = f"{chunk[0] + 1}–{chunk[-1] + 1}"
                content = f"Grid {chunk_no + 1}/{len(chunks)} — {cells}"
            pages.append(GridPage(content, data))

    return GridResult(pages=pages, survivors=survivors, pruned=pruned)


def _chunks(total: int, size: int) -> list[range]:
    """Cell indices split into ``size``-sized chunks, in order."""
    return [range(i, min(i + size, total)) for i in range(0, total, size)]


def _encode_upload(
    canvas: Image.Image, cap: int = MAX_UPLOAD_BYTES
) -> bytes:
    """WebP-encode a stitched canvas under Discord's attachment cap.

    Quality steps down while the bytes stay above the cap; an image whose
    finest step is still too big is downscaled and re-encoded, so the
    result fits a non-boosted upload.
    """
    image = canvas
    while True:
        quality = 85
        while quality > 40:
            data = _webp_bytes(image, quality)
            if len(data) <= cap * UPLOAD_HEADROOM:
                return data
            quality -= 15
        data = _webp_bytes(image, quality)
        if len(data) <= cap or max(image.size) <= 256:
            # either it fits, or there is no resolution left to trade
            return data
        image = image.resize(
            (
                max(64, int(image.width / math.sqrt(2))),
                max(64, int(image.height / math.sqrt(2))),
            ),
            Image.Resampling.LANCZOS,
        )


def _webp_bytes(canvas: Image.Image, quality: int) -> bytes:
    """One WebP encode of ``canvas`` at ``quality``."""
    buf = io.BytesIO()
    canvas.save(buf, "WEBP", quality=quality, method=6, lossless=False)
    return buf.getvalue()


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
