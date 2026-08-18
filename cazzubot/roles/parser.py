"""Parser for the ``roles.manifest`` line format.

The manifest is a line-oriented declarative description of the guild's
roles: ``[Group]`` headers order the role lines below them, one role per
line, ``Name`` optionally followed by `` : `` and whitespace-separated
tokens. ``[preset name]`` sections define permission presets.

Pure and offline-testable; every parse problem is collected (not aborted
on the first one) and reported with a line number and a suggestion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import hikari

from cazzubot.manifest.lines import (
    Issue,
    ManifestError,
    commit_group,
    parse_rename,
    split_name_line,
    suggest,
    validate_renames,
)

# Current Discord permission bits hikari hasn't wrapped yet (values from the
# official API docs — hikari's layout matches Discord for everything it has).
_EXTRA_FLAG_BITS: dict[str, int] = {
    "set_voice_channel_status": 1 << 48,
    "bypass_slowmode": 1 << 52,
}

# discord.py-era flag names the manifest has historically accepted, mapped to
# the canonical Discord permission they denote. Discord's own UI calls
# MANAGE_ROLES "Manage Permissions", USE_VAD "Use Voice Activity", etc.
LEGACY_FLAG_ALIASES: dict[str, str] = {
    "read_messages": "view_channel",
    "external_emojis": "use_external_emojis",
    "external_stickers": "use_external_stickers",
    "mention_everyone": "mention_roles",
    "use_embedded_activities": "start_embedded_activities",
    "use_voice_activation": "use_voice_activity",
    "manage_emojis": "manage_guild_expressions",
    "manage_emojis_and_stickers": "manage_guild_expressions",
    "manage_expressions": "manage_guild_expressions",
    "create_expressions": "create_guild_expressions",
    "create_polls": "send_polls",
    "manage_permissions": "manage_roles",
}

# Every current Discord permission name -> bit (hikari's flags, lowercased,
# plus the bits hikari hasn't wrapped).
CANONICAL_FLAGS: dict[str, int] = {
    flag.name.lower(): int(flag)
    for flag in hikari.Permissions
    if flag.value > 0 and flag.name is not None
}
CANONICAL_FLAGS.update(_EXTRA_FLAG_BITS)

# Every flag name the manifest accepts: canonical names + legacy aliases.
VALID_FLAGS: set[str] = set(CANONICAL_FLAGS) | set(LEGACY_FLAG_ALIASES)


def flag_bit(name: str) -> int:
    """The permission bit for a canonical or legacy flag name."""
    bit = CANONICAL_FLAGS.get(name)
    if bit is not None:
        return bit
    canonical = LEGACY_FLAG_ALIASES[name]
    return CANONICAL_FLAGS[canonical]


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
        """All role names across every group, in order."""
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

    def commit_preset() -> None:
        """Commit an in-progress preset section (duplicates are reported)."""
        nonlocal preset, preset_flags
        if preset is None:
            return
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

    def close_sections() -> None:
        """Finalize any in-progress preset/group before a new header."""
        nonlocal group, roles
        commit_preset()
        commit_group(
            group,
            roles,
            groups,
            seen_titles,
            issues,
            group_word="group",
            items_field="roles",
        )
        group = None
        roles = []

    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            # a blank line ends an in-progress preset section, so role
            # lines may follow presets without a [Group] header
            if preset is not None:
                commit_preset()
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
                            + suggest(token, VALID_FLAGS)
                            + " (if this is a role line, end the preset section with a blank line first)",
                        )
                    )
                    continue
                preset_flags.append(LEGACY_FLAG_ALIASES.get(token, token))
            continue

        if group is None:
            group = GroupSpec(title=None, line=line_no)  # implicit group
        name_part, token_part = split_name_line(
            raw, kind="role", line_no=line_no, issues=issues
        )

        parsed = parse_rename(
            name_part, kind="role", line_no=line_no, issues=issues
        )
        if parsed is None:
            continue
        name, renamed_from = parsed
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
                        + suggest(role.preset, presets),
                    )
                )

    # rename validation: no chains (A->B then B->C) and no duplicate
    # sources (A->B and A->C would fight for the same live role)
    validate_renames(
        (role for g in groups for role in g.roles), issues
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
                        + suggest(flag, VALID_FLAGS),
                    )
                )
                continue
            (grants if token[0] == "+" else revokes).add(
                LEGACY_FLAG_ALIASES.get(flag, flag)
            )
            continue
        candidates = (
            ["hoist", "mentionable", "icon", "preset"]
            + list(NAMED_COLORS)
            + list(VALID_FLAGS)
        )
        issues.append(
            Issue(
                line_no,
                f"unknown token {token!r}" + suggest(token, candidates),
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


def _expand3(hex3: str) -> str:
    """Expand a 3-digit hex color to 6 digits."""
    return "#" + "".join(c * 2 for c in hex3[1:])
