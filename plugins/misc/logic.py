"""Misc plugin — pure helpers for server-utility commands (PIL only)."""

import io
import re
from dataclasses import dataclass

import pendulum
from PIL import Image

BANNER_RATIO = 16 / 9
BANNER_MAX_SIZE = (1920, 1080)

# Discord's snowflake epoch: 2015-01-01T00:00:00Z, in milliseconds.
_DISCORD_EPOCH_MS = 1420070400000

# https://discord.com/channels/<guild|@me>/<channel>/<message>[?...]
_MESSAGE_LINK_RE = re.compile(
    r"^https?://(?:discord|discordapp)\.com/channels/"
    r"(?P<guild>@me|\d+)/(?P<channel>\d+)/(?P<message>\d+)"
)


@dataclass(frozen=True, slots=True)
class MessageLink:
    """A parsed Discord message link (``guild_id`` is ``@me`` for DMs)."""

    guild_id: str
    channel_id: int
    message_id: int


def parse_message_link(text: str) -> MessageLink | None:
    """Parse a Discord message link; None when ``text`` isn't one."""
    match = _MESSAGE_LINK_RE.match(text.strip())
    if match is None:
        return None
    return MessageLink(
        guild_id=match.group("guild"),
        channel_id=int(match.group("channel")),
        message_id=int(match.group("message")),
    )


def snowflake_time(message_id: int) -> pendulum.DateTime:
    """When a Discord snowflake (message id) was created, UTC."""
    created_ms = (message_id >> 22) + _DISCORD_EPOCH_MS
    return pendulum.from_timestamp(created_ms / 1000, tz="UTC")


def prepare_banner(data: bytes) -> bytes:
    """Center-crop ``data`` to 16:9 and return JPEG bytes.

    Discord guild banners must be 16:9. Downscale-only (never upscale):
    a small source keeps its resolution after cropping.
    """
    image = Image.open(io.BytesIO(data))
    image = image.convert("RGB")
    image = _center_crop(image, BANNER_RATIO)
    image = _fit_max(image, BANNER_MAX_SIZE)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def _center_crop(image: Image.Image, ratio: float) -> Image.Image:
    """Crop to ``ratio`` (width/height), keeping the middle."""
    width, height = image.size
    target_width = int(height * ratio)
    if target_width <= width:
        left = (width - target_width) // 2
        return image.crop((left, 0, left + target_width, height))
    target_height = int(width / ratio)
    top = (height - target_height) // 2
    return image.crop((0, top, width, top + target_height))


def _fit_max(image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    """Shrink to fit within ``max_size`` (aspect preserved), else as-is."""
    width, height = image.size
    scale = min(max_size[0] / width, max_size[1] / height)
    if scale >= 1:
        return image
    new_size = (int(width * scale), int(height * scale))
    return image.resize(new_size, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType] PIL stubs
