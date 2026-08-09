"""Board plugin — pure logic: filtering and hashing.

Week math lives in ``cazzubot.utils`` (the board week runs Sunday 00:00
UTC → next Sunday 00:00 UTC). No discord imports here — see
``tests/core/test_csr_boundary.py``.
"""

import hashlib
import io
from datetime import datetime

import pendulum
from PIL import Image

MAX_IMAGES = 50  # grid cells (matches the poll plugin's item cap)
CONTENT_LIMIT = 2000  # Discord message content limit


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
