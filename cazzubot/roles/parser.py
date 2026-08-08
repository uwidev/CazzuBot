"""Parser for the ``roles.manifest`` line format.

The manifest is a line-oriented declarative description of the guild's
roles: ``[Group]`` headers order the role lines below them, one role per
line, ``Name`` optionally followed by `` : `` and whitespace-separated
tokens. ``[preset name]`` sections define permission presets.

Pure and offline-testable; every parse problem is collected (not aborted
on the first one) and reported with a line number and a suggestion.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import hikari
from typing_extensions import override

# The Discord permission flag names, lowercased (both frameworks expose the
# same words; hikari's are UPPER_SNAKE, discord.py's are lower_snake).
VALID_FLAGS: set[str] = {
    flag.name.lower()
    for flag in hikari.Permissions
    if flag.value > 0 and flag.name is not None
}

# discord.py's named palette (values from the corresponding Colour
# classmethods), so a manifest can say ``red`` instead of ``#e74c3c``.
NAMED_COLORS: dict[str, str] = {
    "teal": "#1abc9c",
    "dark_teal": "#11806a",
    "green": "#2ecc71",
    "dark_green": "#1f8b4c",
    "blue": "#3498db",
    "dark_blue": "#206694",
    "purple": "#9b59b6",
    "dark_purple": "#71368a",
    "magenta": "#e91e63",
    "dark_magenta": "#ad1457",
    "gold": "#f1c40f",
    "dark_gold": "#c27c0e",
    "orange": "#e67e22",
    "dark_orange": "#a84300",
    "red": "#e74c3c",
    "dark_red": "#992d22",
    "lighter_grey": "#95a5a6",
    "light_grey": "#979c9f",
    "dark_grey": "#607d8b",
    "darker_grey": "#546e7a",
    "og_blurple": "#7289da",
    "blurple": "#5865f2",
    "greyple": "#99aab5",
    "fuchsia": "#eb459e",
    "yellow": "#faa61a",
}

_IDENT = re.compile(r"^[a-z0-9_-]+$")
_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX3 = re.compile(r"^#[0-9a-fA-F]{3}$")


@dataclass(frozen=True, slots=True)
class RoleSpec:
    """One role line from the manifest.

    ``renamed_from`` is set when the line reads ``OLD->NEW``: the live role
    ``OLD`` is renamed to ``name`` when the manifest is applied.
    """

    name: str
    line: int
    color: str | None = None
    hoist: bool = False
    mentionable: bool = False
    icon: str | None = None
    preset: str | None = None
    grants: frozenset[str] = frozenset()
    revokes: frozenset[str] = frozenset()
    renamed_from: str | None = None


@dataclass(frozen=True, slots=True)
class GroupSpec:
    """A group: an optional marker role plus its member roles.

    ``title`` is the header text without brackets; the marker role's name
    is ``[title]`` (see :func:`marker_name`). ``title=None`` means the
    group has no marker — its roles are header-less lines, positioned
    above the next marker (or at the very top).
    """

    title: str | None
    line: int
    roles: tuple[RoleSpec, ...] = ()


def marker_name(title: str) -> str:
    """The Discord role name a group header ``[title]`` maps to."""
    return f"[{title}]"


def is_marker(name: str) -> bool:
    """True when a role name uses the group-marker convention ``[X]``."""
    return len(name) >= 3 and name.startswith("[") and name.endswith("]")


@dataclass(frozen=True, slots=True)
class PresetSpec:
    """A ``[preset name]`` section: named permission flags."""

    name: str
    line: int
    flags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Manifest:
    """The parsed manifest: presets plus ordered groups."""

    presets: dict[str, PresetSpec] = field(default_factory=dict)
    groups: tuple[GroupSpec, ...] = ()

    def role_names(self) -> tuple[str, ...]:
        return tuple(
            role.name for group in self.groups for role in group.roles
        )

    def ordered_names(self) -> tuple[str, ...]:
        """Sidebar order: group-marker roles interleaved with their roles."""
        names: list[str] = []
        for group in self.groups:
            if group.title is not None:
                names.append(marker_name(group.title))
            names.extend(role.name for role in group.roles)
        return tuple(names)

    def renames(self) -> tuple[tuple[int, str, str], ...]:
        """(line, old name, new name) for every ``OLD->NEW`` role line."""
        return tuple(
            (role.line, role.renamed_from, role.name)
            for group in self.groups
            for role in group.roles
            if role.renamed_from is not None
        )

    def effective_permissions(self, spec: RoleSpec) -> frozenset[str]:
        """final = preset ∪ grants − revokes (revokes win)."""
        base: set[str] = set()
        if spec.preset is not None:
            base |= set(self.presets[spec.preset].flags)
        base |= set(spec.grants)
        base -= set(spec.revokes)
        return frozenset(base)


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


def parse(text: str) -> Manifest:
    """Parse manifest text, raising :class:`ManifestError` on any problem."""
    issues: list[Issue] = []
    presets: dict[str, PresetSpec] = {}
    groups: list[GroupSpec] = []
    seen_roles: dict[str, int] = {}

    # current section being built
    preset: PresetSpec | None = None
    preset_flags: list[str] = []
    group: GroupSpec | None = None
    roles: list[RoleSpec] = []
    seen_titles: dict[str, int] = {}

    def close_sections() -> None:
        """Finalize any in-progress preset/group before a new header."""
        nonlocal preset, preset_flags, group, roles
        if preset is not None:
            if preset.name in presets:
                issues.append(
                    Issue(preset.line, f"duplicate preset {preset.name!r}")
                )
            else:
                presets[preset.name] = PresetSpec(
                    name=preset.name,
                    line=preset.line,
                    flags=frozenset(preset_flags),
                )
        if group is not None:
            if group.title is not None and group.title in seen_titles:
                issues.append(
                    Issue(
                        group.line,
                        f"duplicate group {group.title!r} (first at line {seen_titles[group.title]})",
                    )
                )
            elif group.title is not None:
                seen_titles[group.title] = group.line
                groups.append(
                    GroupSpec(group.title, group.line, tuple(roles))
                )
            else:
                # implicit group — commit only if it has roles
                if roles:
                    groups.append(
                        GroupSpec(None, group.line, tuple(roles))
                    )
        preset = None
        preset_flags = []
        group = None
        roles = []

    def close_preset() -> None:
        """Commit an open preset section (a blank line ends it)."""
        nonlocal preset, preset_flags
        if preset is not None:
            if preset.name in presets:
                issues.append(
                    Issue(preset.line, f"duplicate preset {preset.name!r}")
                )
            else:
                presets[preset.name] = PresetSpec(
                    name=preset.name,
                    line=preset.line,
                    flags=frozenset(preset_flags),
                )
            preset = None
            preset_flags = []

    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            # a blank line ends an in-progress preset section, so role
            # lines may follow presets without a [Group] header
            if preset is not None:
                close_preset()
            continue
        if stripped.startswith("#"):
            continue

        if stripped.startswith("["):
            if not stripped.endswith("]"):
                issues.append(Issue(line_no, "unclosed section header"))
                continue
            content = stripped[1:-1].strip()
            if not content:
                issues.append(Issue(line_no, "empty section header"))
                continue
            close_sections()
            if content.startswith("preset "):
                name = content[len("preset ") :].strip()
                if not _IDENT.fullmatch(name):
                    issues.append(
                        Issue(
                            line_no,
                            f"invalid preset name {name!r} (preset names: lowercase letters, digits, `_`, `-`)",
                        )
                    )
                    continue
                preset = PresetSpec(name=name, line=line_no)
            else:
                group = GroupSpec(title=content, line=line_no)
            continue

        if preset is not None:
            tokens = stripped.split()
            for token in tokens:
                if token == "#":
                    break
                if token not in VALID_FLAGS:
                    issues.append(
                        Issue(
                            line_no,
                            f"unknown permission {token!r}"
                            + _suggest(token, VALID_FLAGS)
                            + " (if this is a role line, end the preset section with a blank line first)",
                        )
                    )
                    continue
                preset_flags.append(token)
            continue

        if group is None:
            group = GroupSpec(title=None, line=line_no)  # implicit group
        if " : " in stripped:
            name_part, _, token_part = stripped.partition(" : ")
        else:
            name_part, token_part = stripped, ""
        raw_name = name_part
        name_part = name_part.strip()
        if name_part != raw_name:
            issues.append(
                Issue(
                    line_no,
                    "role name has leading/trailing whitespace — verbatim names can't round-trip",
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
            name, renamed_from = new, old
        else:
            name = name_part
        if not name:
            issues.append(Issue(line_no, "empty role name"))
            continue
        if name == "@everyone":
            issues.append(
                Issue(
                    line_no,
                    "@everyone is reserved — the engine pins it at the bottom and never manages it",
                )
            )
        if is_marker(name):
            issues.append(
                Issue(
                    line_no,
                    f"{name!r} looks like a group marker — declare it as a [header] line instead of a role line",
                )
            )
        if name in seen_roles:
            issues.append(
                Issue(
                    line_no,
                    f"duplicate role {name!r} (first at line {seen_roles[name]})",
                )
            )
        seen_roles[name] = line_no
        roles.append(
            _parse_role(
                name,
                line_no,
                token_part,
                issues,
                renamed_from=renamed_from,
            )
        )
        continue

    close_sections()

    # preset references resolve order-independently: validate at the end
    for g in groups:
        for role in g.roles:
            if role.preset is not None and role.preset not in presets:
                issues.append(
                    Issue(
                        role.line,
                        f"role {role.name!r} references unknown preset {role.preset!r}"
                        + _suggest(role.preset, presets),
                    )
                )

    # rename validation: no chains (A->B then B->C)
    rename_by_old = {
        role.renamed_from: role
        for g in groups
        for role in g.roles
        if role.renamed_from is not None
    }
    for old, role in rename_by_old.items():
        if role.name in rename_by_old:
            issues.append(
                Issue(
                    role.line,
                    f"rename chain not supported: {old!r} -> {role.name!r} is itself renamed elsewhere",
                )
            )

    if issues:
        raise ManifestError(issues)
    return Manifest(presets=presets, groups=tuple(groups))


def _parse_role(
    name: str,
    line_no: int,
    token_part: str,
    issues: list[Issue],
    *,
    renamed_from: str | None = None,
) -> RoleSpec:
    color: str | None = None
    hoist = False
    mentionable = False
    icon: str | None = None
    preset: str | None = None
    grants: set[str] = set()
    revokes: set[str] = set()

    for token in token_part.split():
        if token == "#":
            break
        if token in ("hoist", "mentionable"):
            if token == "hoist":
                hoist = True
            else:
                mentionable = True
            continue
        if token.startswith("#"):
            if _HEX6.fullmatch(token) or _HEX3.fullmatch(token):
                if color is not None:
                    issues.append(Issue(line_no, "duplicate color token"))
                    continue
                color = token if len(token) == 7 else _expand3(token)
            else:
                issues.append(Issue(line_no, f"invalid color {token!r}"))
            continue
        if token in NAMED_COLORS:
            if color is not None:
                issues.append(Issue(line_no, "duplicate color token"))
                continue
            color = NAMED_COLORS[token]
            continue
        if token.startswith("preset:"):
            if preset is not None:
                issues.append(Issue(line_no, "duplicate preset token"))
                continue
            preset = token[len("preset:") :]
            continue
        if token.startswith("icon:"):
            if icon is not None:
                issues.append(Issue(line_no, "duplicate icon token"))
                continue
            icon = token[len("icon:") :]
            if not icon:
                issues.append(Issue(line_no, "empty icon token"))
            continue
        if token.startswith(("+", "-")):
            flag = token[1:]
            if flag not in VALID_FLAGS:
                issues.append(
                    Issue(
                        line_no,
                        f"unknown permission {flag!r}"
                        + _suggest(flag, VALID_FLAGS),
                    )
                )
                continue
            (grants if token[0] == "+" else revokes).add(flag)
            continue
        candidates = (
            ["hoist", "mentionable", "icon", "preset"]
            + list(NAMED_COLORS)
            + list(VALID_FLAGS)
        )
        issues.append(
            Issue(
                line_no,
                f"unknown token {token!r}" + _suggest(token, candidates),
            )
        )

    return RoleSpec(
        name=name,
        line=line_no,
        color=color,
        hoist=hoist,
        mentionable=mentionable,
        icon=icon,
        preset=preset,
        grants=frozenset(grants),
        revokes=frozenset(revokes),
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


def _expand3(hex3: str) -> str:
    """Expand a 3-digit hex color to 6 digits."""
    return "#" + "".join(c * 2 for c in hex3[1:])
