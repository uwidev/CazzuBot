"""Shared channel-snapshot fixtures for the channels engine tests."""

from __future__ import annotations

from typing import Any, cast

from cazzubot.channels.snapshot import ChannelSnapshot


def ch(
    id: str,
    name: str,
    kind: str = "text",
    cat: str | None = None,
    pos: int = 0,
    nsfw: bool = False,
    slow: int = 0,
    **voice: object,
) -> ChannelSnapshot:
    d: ChannelSnapshot = {
        "id": id,
        "name": name,
        "kind": kind,
        "category": cat,
        "position": pos,
        "nsfw": nsfw,
        "slowmode": slow,
    }
    if kind in ("voice", "stage"):
        d.update(bitrate=64, limit=0, region=None, quality="auto")
    d.update(cast(Any, voice))
    return d


SNAPSHOT: list[ChannelSnapshot] = [
    ch("0", "welcome"),
    ch("1", "general", slow=5),
    ch("2", "lobby", "voice"),
    ch("3", "Games", "category"),
    ch("4", "minecraft", cat="Games"),
    ch("5", "voice-chat", "voice", cat="Games", bitrate=96),
    ch("6", "Info", "category", pos=1),
    ch("7", "rules", cat="Info"),
    ch("8", "announcements", "announcement", cat="Info", pos=1),
]


def mutated(name: str, **fields: Any) -> list[ChannelSnapshot]:
    """SNAPSHOT with one channel's fields replaced by ``fields``."""
    return [
        cast(Any, {**dict(c), **fields}) if c["name"] == name else c
        for c in SNAPSHOT
    ]
