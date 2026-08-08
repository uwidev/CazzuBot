"""Render a role snapshot into the ``roles.manifest`` line format.

Turns the flat role list produced by the CLI's ``snapshot fetch`` into a
declarative manifest: permission presets (derived from named source roles),
roles in exact sidebar positional order, group-marker roles (named ``[X]``)
emitted as ``[X]`` headers, and the format cheatsheet (with the full
permission list) at the top. Pure function — offline-testable, no discord
connection needed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cazzubot.roles.parser import VALID_FLAGS, is_marker
from cazzubot.roles.snapshot import RoleSnapshot

EVERYONE = "@everyone"


def cheatsheet(
    source: str | None = None, exported: str | None = None
) -> str:
    """The comment block every exported manifest starts with."""
    lines = [
        "# roles.manifest — declarative role manifest (generated; edit freely)",
    ]
    if source:
        lines.append(f"# Generated from {source}")
    if exported:
        lines.append(f"# Exported {exported}")
    lines.extend(
        [
            "#",
            "# ── line format ──",
            '#   [Group]              group-marker role (named "[Group]" on',
            "#                        discord); everything below it until the",
            "#                        next marker belongs to this group",
            "#   Role Name            one role per line, verbatim Discord name",
            "#   Role Name : token …  tokens: hoist | mentionable | #rrggbb |",
            "#                        preset:<name> | +flag | -flag | icon:<emoji>",
            "#   Old Name->New Name    rename a role (rewritten to just the",
            "#                        new name after a successful apply)",
            "#   [preset name]        permission preset section; flag lines below",
            "#   # comment            blank lines and # comments are ignored",
            "#",
            "# ── all discord permissions ──",
            "#   (bare in presets; +flag / -flag on role lines)",
        ]
    )
    line = "#   "
    for flag in sorted(VALID_FLAGS):
        candidate = f"#   {flag}" if line == "#   " else f"{line} {flag}"
        if len(candidate) > 75:
            lines.append(line)
            line = f"#   {flag}"
        else:
            line = candidate
    if line != "#   ":
        lines.append(line)
    lines.append("#   (final perms = preset ∪ +flags − −flags)")
    return "\n".join(lines)


def render_manifest(
    roles: Sequence[RoleSnapshot],
    *,
    presets: Mapping[str, str] | None = None,
    source: str | None = None,
    exported: str | None = None,
) -> str:
    """Render a role snapshot (fetch_roles.py output) as manifest text.

    ``presets`` maps a preset name to the name of a live role whose current
    permissions become the preset's flags (default: ``member`` from
    ``@everyone``). Managed roles are listed name-only (they cannot be
    edited, only positioned). ``source`` is a provenance note for the
    header; ``exported`` is the export timestamp, shown as a header comment.
    """
    source_presets = (
        presets if presets is not None else {"member": "@everyone"}
    )
    preset_flags = _derive_presets(roles, source_presets)

    lines = [cheatsheet(source, exported), ""]
    for name, flags in preset_flags:
        lines.extend(_preset_block(name, flags))
    if preset_flags:
        # a blank line terminates the preset section, so header-less role
        # lines can follow it (guilds without marker roles)
        lines.append("")
    for role in _ordered(roles):
        if role["name"] == EVERYONE:
            continue
        if is_marker(role["name"]):
            lines.append("")
            lines.append(role["name"])  # the marker's name IS the header
        elif role["managed"]:
            lines.append(role["name"])
        else:
            lines.append(role["name"] + _tokens(role, preset_flags))
    lines.append("")
    lines.append(
        f"# {sum(1 for r in roles if r['name'] != EVERYONE)} roles listed (excl. @everyone); {sum(1 for r in roles if r['managed'])} managed"
    )
    lines.append("# vim: ft=txt :")
    return "\n".join(lines) + "\n"


def _ordered(roles: Sequence[RoleSnapshot]) -> list[RoleSnapshot]:
    """Roles in sidebar order: highest position first."""
    return sorted(
        (r for r in roles if r["name"] != EVERYONE),
        key=lambda r: r["position"],
    )


def _derive_presets(
    roles: Sequence[RoleSnapshot], source: Mapping[str, str]
) -> list[tuple[str, list[str]]]:
    by_name = {r["name"]: r for r in roles}
    out: list[tuple[str, list[str]]] = []
    for name, role_name in source.items():
        role = by_name.get(role_name)
        if role is None:
            continue
        flags = sorted(role["permissions"])
        if flags:
            out.append((name, flags))
    return out


def _preset_block(name: str, flags: list[str]) -> list[str]:
    block = [f"[preset {name}]"]
    line = ""
    for flag in flags:
        candidate = flag if not line else f"{line} {flag}"
        if len(candidate) > 75:
            block.append(line)
            line = flag
        else:
            line = candidate
    block.append(line)
    return block


def _tokens(
    role: RoleSnapshot, presets: list[tuple[str, list[str]]]
) -> str:
    tokens: list[str] = []
    if role["color"]:
        tokens.append(role["color"])
    if role["hoisted"]:
        tokens.append("hoist")
    if role["mentionable"]:
        tokens.append("mentionable")
    icon = role.get("icon")
    if icon and not icon.startswith("http"):
        tokens.append(f"icon:{icon}")

    perms = set(role["permissions"])
    if perms:
        tokens.extend(_perm_tokens(perms, presets))
    return f" : {' '.join(tokens)}" if tokens else ""


def _perm_tokens(
    perms: set[str], presets: list[tuple[str, list[str]]]
) -> list[str]:
    """Tokenize permissions: best preset match + +/- diffs, else raw flags."""
    if not presets:
        return [f"+{f}" for f in sorted(perms)]
    best: tuple[int, str, set[str]] | None = None
    for name, flags in presets:
        base = set(flags)
        symdiff = len(perms ^ base)
        if best is None or symdiff < best[0]:
            best = (symdiff, name, base)
    assert best is not None  # presets list is non-empty here
    _, name, base = best

    tokens: list[str] = []
    missing = perms - base
    extra = base - perms
    if base & perms or not perms - base:
        # preset matches at least partially — use it plus the diff
        tokens.append(f"preset:{name}")
        tokens.extend(f"+{f}" for f in sorted(missing))
        tokens.extend(f"-{f}" for f in sorted(extra))
    else:
        tokens.extend(f"+{f}" for f in sorted(perms))
    return tokens
