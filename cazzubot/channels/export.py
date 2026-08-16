"""Render a channel snapshot into the ``channels.manifest`` line format.

Turns the flat channel list produced by a live fetch into a declarative
manifest: Discord categories become ``[Category]`` headers (the manifest
leanly adds diff/apply on top of Discord's native grouping), channels are
listed in exact rendering order — uncategorized text/voice first, then
categories, each with its text-section channels then voice-section
channels — and every Overview field except the topic is tokenized. Pure
function — offline-testable, no discord connection needed.
"""

from __future__ import annotations

from collections.abc import Sequence

from cazzubot.channels.snapshot import (
    ChannelSnapshot,
    SLOWMODE_KINDS,
    VOICE_KINDS,
)

# rendering order of Discord's channel sections: the text section (text,
# announcement, forum) renders above the voice section (voice, stage)
_SECTION: dict[str, int] = {
    "text": 0,
    "announcement": 0,
    "forum": 0,
    "voice": 1,
    "stage": 1,
}

# discord.py exposes the server-side video quality int; the manifest uses
# the UI labels (Discord's Overview picker). The API only accepts 1 (auto)
# and 2 (1080p) — 720p was removed server-side.
QUALITY_VALUES: dict[str, int] = {"auto": 1, "1080": 2}

# voice-channel defaults — attrs at their default are omitted from the
# manifest so absence round-trips as "default"
BITRATE_DEFAULT_KBPS = 64
LIMIT_DEFAULT = 0  # 0 = unlimited


def cheatsheet(
    source: str | None = None, exported: str | None = None
) -> str:
    """The comment block every exported manifest starts with."""
    lines = [
        "# channels.manifest — declarative channel manifest (generated; edit freely)",
    ]
    if source:
        lines.append(f"# Generated from {source}")
    if exported:
        lines.append(f"# Exported {exported}")
    lines.extend(
        [
            "#",
            "# ── line format ──",
            "#   [Category]         category header — maps to a Discord",
            "#                       category; everything below it until the",
            "#                       next header belongs to it. Channels before",
            "#                       the first header are uncategorized.",
            "#   Channel Name        one channel per line, verbatim name",
            "#   Channel Name : token …  tokens: type:text|announcement|voice|",
            "#                       forum|stage (default text) | nsfw |",
            "#                       slowmode:<sec> | bitrate:<kbps> |",
            "#                       limit:<n> | region:<code|auto> |",
            "#                       quality:auto|1080",
            "#   Old Name->New Name  rename a channel (rewritten to just the",
            "#                       new name after a successful apply)",
            "#   # comment           blank lines and # comments are ignored",
            "#",
            "#   The Overview fields covered: name, type, category, position,",
            "#   slowmode, nsfw, bitrate, user limit, region, video quality.",
            "#   The channel topic and permission overwrites are NOT managed.",
        ]
    )
    return "\n".join(lines)


def render_manifest(
    channels: Sequence[ChannelSnapshot],
    *,
    source: str | None = None,
    exported: str | None = None,
) -> str:
    """Render a channel snapshot as manifest text.

    ``source`` is a provenance note for the header; ``exported`` is the
    export timestamp, shown as a header comment.
    """
    lines = [cheatsheet(source, exported), ""]
    groups = _group_snapshot(channels)
    for title, members in groups:
        if title is not None:
            lines.append("")
            lines.append(f"[{title}]")
        for ch in members:
            lines.append(ch["name"] + _tokens(ch))
    lines.append("")
    listed = [ch for ch in channels if not ch.get("unsupported")]
    lines.append(
        f"# {len(listed)} channels listed; {sum(1 for ch in listed if ch['kind'] == 'category')} categories"
    )
    lines.append("# vim: ft=txt :")
    return "\n".join(lines) + "\n"


def _group_snapshot(
    channels: Sequence[ChannelSnapshot],
) -> list[tuple[str | None, list[ChannelSnapshot]]]:
    """Snapshot → [(category name | None, channels in render order)]."""
    by_parent: dict[str | None, list[ChannelSnapshot]] = {}
    for ch in channels:
        if ch["kind"] == "category" or ch.get("unsupported"):
            continue
        by_parent.setdefault(ch["category"], []).append(ch)

    def sort_key(ch: ChannelSnapshot) -> tuple[int, int, str]:
        return (
            _SECTION.get(ch["kind"], 0),
            ch["position"],
            ch["kind"],
        )

    # categories in position order; uncategorized group (None) first
    cats = sorted(
        (ch for ch in channels if ch["kind"] == "category"),
        key=lambda ch: ch["position"],
    )
    groups: list[tuple[str | None, list[ChannelSnapshot]]] = []
    if None in by_parent:
        groups.append((None, sorted(by_parent[None], key=sort_key)))
    for cat in cats:
        groups.append(
            (
                cat["name"],
                sorted(by_parent.get(cat["name"], []), key=sort_key),
            )
        )
    # a category header referenced by children but absent from the live
    # snapshot is impossible — children only reference live categories
    return groups


def _tokens(ch: ChannelSnapshot) -> str:
    tokens: list[str] = []
    kind = ch["kind"]
    if kind != "text":
        tokens.append(f"type:{kind}")
    if ch.get("nsfw"):
        tokens.append("nsfw")
    if kind in SLOWMODE_KINDS and ch["slowmode"]:
        tokens.append(f"slowmode:{ch['slowmode']}")
    if kind in VOICE_KINDS:
        bitrate = ch.get("bitrate")
        if bitrate is not None and bitrate != BITRATE_DEFAULT_KBPS:
            tokens.append(f"bitrate:{bitrate}")
        limit = ch.get("limit")
        if limit is not None and limit != LIMIT_DEFAULT:
            tokens.append(f"limit:{limit}")
        region = ch.get("region")
        if region:
            tokens.append(f"region:{region}")
        quality = ch.get("quality")
        if quality and quality != "auto":
            tokens.append(f"quality:{quality}")
    return f" : {' '.join(tokens)}" if tokens else ""
