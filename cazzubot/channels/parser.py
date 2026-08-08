"""Parser for the ``channels.manifest`` line format.

The manifest is a line-oriented declarative description of the guild's
channels: ``[Category]`` headers declare Discord categories, everything
below a header until the next one belongs to that category, one channel
per line, ``Name`` optionally followed by `` : `` and whitespace-separated
tokens. Channels before the first header are uncategorized (they render at
the top of Discord's channel list).

Discord's *native* grouping — categories — is exactly what the headers
map to; the manifest adds the declarative diff/apply machinery on top.

Pure and offline-testable; every parse problem is collected (not aborted
on the first one) and reported with a line number and a suggestion.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from typing_extensions import override

from cazzubot.channels.snapshot import (
    KINDS,
    SLOWMODE_KINDS,
    VOICE_KINDS,
)

_DIGITS = re.compile(r"^[0-9]+$")

# slowmode bounds — Discord accepts 0..21600 seconds
SLOWMODE_MAX = 21600


@dataclass(frozen=True, slots=True)
class ChannelSpec:
    """One channel line from the manifest.

    ``kind`` defaults to ``text``. ``renamed_from`` is set when the line
    reads ``OLD->NEW``: the live channel ``OLD`` is renamed to ``name``
    when the manifest is applied.
    """

    name: str
    line: int
    kind: str = "text"
    nsfw: bool = False
    slowmode: int = 0
    bitrate: int | None = None
    limit: int | None = None
    region: str | None = None
    quality: str | None = None
    renamed_from: str | None = None


@dataclass(frozen=True, slots=True)
class GroupSpec:
    """A group: a category header plus its member channels.

    ``title`` is the header text without brackets; the Discord category's
    name is ``title`` itself. ``title=None`` means the group has no
    category — its channels are uncategorized, positioned above the next
    category (Discord renders uncategorized channels at the top).
    """

    title: str | None
    line: int
    channels: tuple[ChannelSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class Manifest:
    """The parsed manifest: ordered groups of channels."""

    groups: tuple[GroupSpec, ...] = ()

    def channel_names(self) -> tuple[str, ...]:
        return tuple(
            ch.name for group in self.groups for ch in group.channels
        )

    def ordered_names(self) -> tuple[str, ...]:
        """Guild listing order: category names interleaved with channels."""
        names: list[str] = []
        for group in self.groups:
            if group.title is not None:
                names.append(group.title)
            names.extend(ch.name for ch in group.channels)
        return tuple(names)

    def titles(self) -> tuple[str | None, ...]:
        return tuple(group.title for group in self.groups)

    def renames(self) -> tuple[tuple[int, str, str], ...]:
        """(line, old name, new name) for every ``OLD->NEW`` channel line."""
        return tuple(
            (ch.line, ch.renamed_from, ch.name)
            for group in self.groups
            for ch in group.channels
            if ch.renamed_from is not None
        )


@dataclass(frozen=True, slots=True)
class Issue:
    """One parse problem: line number plus human message."""

    line: int
    message: str

    @override
    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


class ManifestError(ValueError):
    """Raised when a manifest has any parse problems (all collected)."""

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__(f"{len(issues)} manifest error(s)")
        self.issues = issues


def _suggest(word: str, candidates: Iterable[str]) -> str:
    matches = difflib.get_close_matches(word, list(candidates), n=1)
    if not matches:
        return ""
    return f" — did you mean {matches[0]!r}?"


def _name_roundtrips(name: str) -> bool:
    """True when a channel name round-trips through the line format.

    Mirrors the executor's representability rules: names the parser
    would re-read differently (``->`` rename syntax, `` : `` token
    separator, trailing `` :``, ``[``-prefixed header syntax,
    ``#``-prefixed comment syntax, padded or whitespace-only names) are
    rejected so an applied rename can never leave the manifest
    unparseable.
    """
    return bool(
        name.strip()
        and name == name.strip()
        and "->" not in name
        and " : " not in name
        and not name.endswith(" :")
        and not name.startswith("[")
        and not name.startswith("#")
    )


def parse(text: str) -> Manifest:
    """Parse manifest text, raising :class:`ManifestError` on any problem."""
    issues: list[Issue] = []
    groups: list[GroupSpec] = []
    seen_names: dict[str, int] = {}
    seen_titles: dict[str, int] = {}

    group: GroupSpec | None = None
    channels: list[ChannelSpec] = []

    def close_group() -> None:
        nonlocal group, channels
        if group is not None:
            if group.title is not None and group.title in seen_titles:
                issues.append(
                    Issue(
                        group.line,
                        f"duplicate category {group.title!r} (first at line {seen_titles[group.title]})",
                    )
                )
            elif group.title is not None:
                seen_titles[group.title] = group.line
                groups.append(
                    GroupSpec(group.title, group.line, tuple(channels))
                )
            else:
                # implicit group — commit only if it has channels
                if channels:
                    groups.append(
                        GroupSpec(None, group.line, tuple(channels))
                    )
        group = None
        channels = []

    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("["):
            if not stripped.endswith("]"):
                issues.append(Issue(line_no, "unclosed section header"))
                continue
            content = stripped[1:-1].strip()
            if not content:
                issues.append(Issue(line_no, "empty section header"))
                continue
            if " : " in content:
                issues.append(
                    Issue(
                        line_no,
                        "category headers take no tokens — put tokens on channel lines",
                    )
                )
                continue
            close_group()
            group = GroupSpec(title=content, line=line_no)
            continue

        if group is None:
            group = GroupSpec(title=None, line=line_no)  # implicit group
        # split on the raw line so leading/trailing whitespace in the name
        # is still visible (strip() would hide it)
        if " : " in raw:
            name_part, _, token_part = raw.partition(" : ")
        elif raw.endswith(" :"):
            # ``Name :`` with no tokens — trailing separator
            name_part, token_part = raw[:-2], ""
        else:
            name_part, token_part = raw, ""
        raw_name = name_part
        name_part = name_part.strip()
        if name_part != raw_name:
            issues.append(
                Issue(
                    line_no,
                    "channel name has leading/trailing whitespace — verbatim names can't round-trip",
                )
            )

        renamed_from: str | None = None
        if "->" in name_part:
            old_part, _, new_part = name_part.partition("->")
            old, new = old_part.strip(), new_part.strip()
            if not old:
                issues.append(
                    Issue(
                        line_no,
                        "rename has no old name before '->'",
                    )
                )
                continue
            if not new:
                issues.append(
                    Issue(
                        line_no,
                        "rename has no new name after '->'",
                    )
                )
                continue
            if old == new:
                issues.append(
                    Issue(
                        line_no,
                        f"rename {old!r} -> {old!r} is a no-op",
                    )
                )
                continue
            if "->" in new:
                issues.append(
                    Issue(
                        line_no,
                        f"rename target {new!r} contains '->' — renames can't chain",
                    )
                )
                continue
            if not _name_roundtrips(new):
                issues.append(
                    Issue(
                        line_no,
                        f"rename target {new!r} can't round-trip through the manifest format",
                    )
                )
                continue
            name, renamed_from = new, old
        else:
            name = name_part
        if not name:
            issues.append(Issue(line_no, "empty channel name"))
            continue
        if name.startswith("[") and name.endswith("]"):
            issues.append(
                Issue(
                    line_no,
                    f"{name!r} looks like a category header — declare it as a [header] line instead of a channel line",
                )
            )
        if not _name_roundtrips(name):
            issues.append(
                Issue(
                    line_no,
                    f"channel name {name!r} can't round-trip through the manifest format",
                )
            )
        if name in seen_names:
            issues.append(
                Issue(
                    line_no,
                    f"duplicate channel {name!r} (first at line {seen_names[name]})",
                )
            )
        seen_names[name] = line_no
        channels.append(
            _parse_channel(
                name,
                line_no,
                token_part,
                issues,
                renamed_from=renamed_from,
            )
        )
        continue

    close_group()

    # rename validation: no chains (A->B then B->C) and no duplicate
    # sources (A->B and A->C would fight for the same live channel)
    rename_by_old: dict[str, ChannelSpec] = {}
    for group in groups:
        for ch in group.channels:
            if ch.renamed_from is None:
                continue
            if ch.renamed_from in rename_by_old:
                issues.append(
                    Issue(
                        ch.line,
                        f"duplicate rename source {ch.renamed_from!r} "
                        f"(first renamed at line {rename_by_old[ch.renamed_from].line})",
                    )
                )
                continue
            rename_by_old[ch.renamed_from] = ch
    for old, ch in rename_by_old.items():
        if ch.name in rename_by_old:
            issues.append(
                Issue(
                    ch.line,
                    f"rename chain not supported: {old!r} -> {ch.name!r} is itself renamed elsewhere",
                )
            )

    if issues:
        raise ManifestError(issues)
    return Manifest(groups=tuple(groups))


def _parse_channel(
    name: str,
    line_no: int,
    token_part: str,
    issues: list[Issue],
    *,
    renamed_from: str | None = None,
) -> ChannelSpec:
    kind = "text"
    nsfw = False
    slowmode = 0
    bitrate: int | None = None
    limit: int | None = None
    region: str | None = None
    quality: str | None = None

    for token in token_part.split():
        if token == "#":
            break
        if token == "nsfw":
            nsfw = True
            continue
        if token.startswith("type:"):
            if kind != "text":
                issues.append(Issue(line_no, "duplicate type token"))
                continue
            kind = token[len("type:") :]
            if kind not in KINDS or kind == "category":
                issues.append(
                    Issue(
                        line_no,
                        f"invalid channel type {kind!r}"
                        + _suggest(kind, KINDS),
                    )
                )
                continue
            continue
        if token.startswith("slowmode:"):
            value = token[len("slowmode:") :]
            if not _DIGITS.fullmatch(value):
                issues.append(
                    Issue(
                        line_no,
                        f"invalid slowmode {value!r} (seconds, 0..{SLOWMODE_MAX})",
                    )
                )
                continue
            seconds = int(value)
            if seconds > SLOWMODE_MAX:
                issues.append(
                    Issue(
                        line_no,
                        f"slowmode {seconds} exceeds the 6h maximum ({SLOWMODE_MAX}s)",
                    )
                )
                continue
            slowmode = seconds
            continue
        if token.startswith("bitrate:"):
            value = token[len("bitrate:") :]
            if not _DIGITS.fullmatch(value) or not 1 <= int(value) <= 1024:
                issues.append(
                    Issue(
                        line_no,
                        f"invalid bitrate {value!r} (kbps, 1..1024)",
                    )
                )
                continue
            bitrate = int(value)
            continue
        if token.startswith("limit:"):
            value = token[len("limit:") :]
            if not _DIGITS.fullmatch(value) or int(value) > 99999:
                issues.append(
                    Issue(
                        line_no,
                        f"invalid user limit {value!r} (0 = unlimited; Discord allows up to 99999)",
                    )
                )
                continue
            limit = int(value)
            continue
        if token.startswith("region:"):
            value = token[len("region:") :]
            if not value:
                issues.append(Issue(line_no, "empty region token"))
                continue
            region = value
            continue
        if token.startswith("quality:"):
            value = token[len("quality:") :]
            if value not in ("auto", "1080"):
                issues.append(
                    Issue(
                        line_no,
                        f"invalid video quality {value!r} (auto | 1080 — 720p was removed by Discord)",
                    )
                )
                continue
            quality = value
            continue
        candidates = [
            "nsfw",
            "type",
            "slowmode",
            "bitrate",
            "limit",
            "region",
            "quality",
        ] + [f"type:{k}" for k in KINDS]
        issues.append(
            Issue(
                line_no,
                f"unknown token {token!r}" + _suggest(token, candidates),
            )
        )

    # token applicability: slowmode on voice/stage, voice attrs on
    # text/announcement/forum make no sense — flag them so typos surface
    if slowmode and kind not in SLOWMODE_KINDS:
        issues.append(
            Issue(
                line_no,
                f"slowmode doesn't apply to {kind} channels",
            )
        )
    voice_attrs = (bitrate, limit, region, quality)
    if any(v is not None for v in voice_attrs) and kind not in VOICE_KINDS:
        issues.append(
            Issue(
                line_no,
                f"bitrate/limit/region/quality only apply to voice channels (got {kind})",
            )
        )

    return ChannelSpec(
        name=name,
        line=line_no,
        kind=kind,
        nsfw=nsfw,
        slowmode=slowmode,
        bitrate=bitrate,
        limit=limit,
        region=region,
        quality=quality,
        renamed_from=renamed_from,
    )


def rewrite_renames(
    text: str, renames: Sequence[tuple[int, str, str]]
) -> str:
    """Rewrite applied ``OLD->NEW`` lines to just ``NEW``.

    ``renames`` holds ``(line_no, old, new)`` for rename lines that were
    applied successfully. Everything else in the file is preserved byte
    for byte (comments, blank lines, tokens, the modeline).
    """
    lines = text.splitlines(keepends=True)
    for line_no, old, new in renames:
        idx = line_no - 1
        if 0 <= idx < len(lines):
            lines[idx] = lines[idx].replace(f"{old}->{new}", new, 1)
    return "".join(lines)
