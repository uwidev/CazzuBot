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


def representable_name(name: str) -> bool:
    """True when a channel name round-trips through the line format.

    The one representability rule, shared by the parser (rejects names
    it would re-read differently) and the executor (marks live channels
    the engine can't address): names containing ``->`` (rename syntax)
    or `` : `` (token separator), names ending with `` :`` (the parser's
    trailing-separator branch), names with leading/trailing whitespace,
    names starting with ``[`` (header syntax) or ``#`` (comment syntax),
    and whitespace-only names can't be written unambiguously.
    """
    return bool(
        name.strip()
        and name == name.strip()
        and "->" not in name
        and " : " not in name
        and not name.endswith(" :")
        and not name.startswith("[")
        and not name.startswith("#")
        and not name.isspace()
    )
