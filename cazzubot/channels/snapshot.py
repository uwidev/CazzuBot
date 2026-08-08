"""The channel-snapshot shape shared by the engine and the live executor."""

from __future__ import annotations

from typing import NotRequired, TypedDict

# channel kinds the manifest can declare; anything else in a live guild is
# snapshotted with unsupported=True and never touched by the engine
KINDS: tuple[str, ...] = (
    "text",
    "announcement",
    "voice",
    "forum",
    "stage",
    "category",
)

# kinds that carry the voice-attrs (bitrate / limit / region / quality)
VOICE_KINDS: tuple[str, ...] = ("voice", "stage")

# kinds whose Overview includes a slowmode setting (text channels: the
# channel slowmode; forums: the default thread slowmode)
SLOWMODE_KINDS: tuple[str, ...] = ("text", "announcement", "forum")


class ChannelSnapshot(TypedDict):
    """One guild channel as plain data.

    ``position`` is the raw Discord position (scoped to the channel's
    parent and type bucket — see ``cazzubot.channels.executor``). The
    voice attrs are ``None``/absent for kinds that don't have them.
    """

    id: str
    name: str
    kind: str
    category: str | None
    position: int
    nsfw: bool
    slowmode: int
    bitrate: NotRequired[int | None]
    limit: NotRequired[int | None]
    region: NotRequired[str | None]
    quality: NotRequired[str | None]
    unsupported: NotRequired[bool]
