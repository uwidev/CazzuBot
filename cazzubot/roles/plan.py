"""Diff engine: manifest vs live guild role snapshot → executable plan.

Turns a parsed :class:`Manifest` and a role snapshot (the shape produced by
``scripts/fetch_roles.py``) into a :class:`Plan` of creates / updates /
deletes plus the target top-down order. Pure and offline-testable — the
snapshot is plain dicts, not discord objects.

Reachability: a role is *out of reach* when it sits at or above the bot's
highest role in the sidebar (higher = more powerful). Such roles can be
neither edited nor moved; they are reported, never touched. Managed roles
(bots, boost) are never edited or deleted; they may only be positioned.
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from cazzubot.roles.parser import (
    Manifest,
    RoleSpec,
    marker_name,
)
from cazzubot.roles.snapshot import RoleSnapshot

EVERYONE = "@everyone"

# similarity ratio at which a missing role + unlisted stray get a
# "did you mean rename?" hint in the diff output
RENAME_HINT_RATIO = 0.8


@dataclass(frozen=True, slots=True)
class CreateOp:
    spec: RoleSpec
    permissions: frozenset[str]


@dataclass(frozen=True, slots=True)
class UpdateOp:
    name: str
    id: int
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeleteOp:
    name: str
    id: int
    member_count: int | None = None


@dataclass(frozen=True, slots=True)
class RenameOp:
    """Rename the live role ``old`` to ``new`` (from an ``OLD->NEW`` line)."""

    old: str
    new: str
    line: int


@dataclass(frozen=True, slots=True)
class Plan:
    """The full set of changes the manifest implies."""

    creates: list[CreateOp]
    updates: list[UpdateOp]
    deletes: list[DeleteOp]
    renames: list[RenameOp]
    rename_conflicts: list[str]
    rename_hints: list[tuple[str, str]]
    cleanup_renames: list[RenameOp]
    current_order: list[str]
    target_order: list[str]
    out_of_reach: list[str]
    managed_skipped: list[str]
    strays: list[str]
    unmovable: list[str]
    top_index: int | None

    @property
    def needs_reorder(self) -> bool:
        return self.target_order != self.current_order

    @property
    def reorder_blocked(self) -> bool:
        """True only when a role the reorder can't move would actually move.

        Out-of-reach and managed roles that keep their current position
        don't block reordering the movable part of the sidebar.
        """
        return bool(self.moving_unmovable())

    def moving_unmovable(self) -> list[str]:
        """Roles the reorder can't move that the target order would move.

        Covers unmovable roles (managed/boost, above the bot) whose target
        slot differs, plus any role that would end up *above* the bot's own
        highest role (the bot cannot move roles across its top role).
        """
        current = {name: i for i, name in enumerate(self.current_order)}
        target = {name: i for i, name in enumerate(self.target_order)}
        blockers = [
            name
            for name in self.unmovable
            if name in current
            and name in target
            and current[name] != target[name]
        ]
        if self.top_index is not None:
            blockers.extend(
                name
                for name in current
                if name in target
                and current[name] >= self.top_index
                and target[name] < self.top_index
            )
        return sorted(set(blockers))

    def is_clean(self) -> bool:
        return not (
            self.creates
            or self.updates
            or self.deletes
            or self.renames
            or self.rename_conflicts
            or self.cleanup_renames
            or self.needs_reorder
        )

    @property
    def needs_apply(self) -> bool:
        """Anything that requires mutating the guild (excludes manifest
        cleanup — stale rename lines are fixed by the file rewrite)."""
        return bool(
            self.creates
            or self.updates
            or self.deletes
            or self.renames
            or self.rename_conflicts
            or self.needs_reorder
        )

    def summary(self) -> str:
        bits = [
            f"create {len(self.creates)}",
            f"update {len(self.updates)}",
            f"rename {len(self.renames)}",
            "reorder" if self.needs_reorder else "order ok",
            f"delete {len(self.deletes)}",
        ]
        if self.cleanup_renames:
            bits.append(f"cleanup {len(self.cleanup_renames)}")
        if self.rename_conflicts:
            bits.append(f"{len(self.rename_conflicts)} rename conflicts")
        if self.out_of_reach:
            bits.append(f"{len(self.out_of_reach)} out of reach")
        return " · ".join(bits)

    def render(self) -> str:
        """Human-readable diff for the terminal / boot log."""
        out: list[str] = []
        if self.renames:
            out.append(f"rename {len(self.renames)}:")
            for op in self.renames:
                out.append(f"  ⇄ {op.old} -> {op.new}")
        if self.cleanup_renames:
            out.append(
                f"cleanup {len(self.cleanup_renames)} (rename already applied — manifest line rewritten on apply):"
            )
            for op in self.cleanup_renames:
                out.append(f"  ⇄ {op.old} -> {op.new}")
        if self.rename_conflicts:
            out.append("rename conflicts (new name already exists):")
            for name in self.rename_conflicts:
                out.append(f"  ✖ {name}")
        if self.creates:
            out.append(f"create {len(self.creates)}:")
            for op in self.creates:
                out.append(f"  + {op.spec.name}{_describe(op.spec)}")
        if self.updates:
            out.append(f"update {len(self.updates)}:")
            for op in self.updates:
                out.append(f"  ~ {op.name}")
                for field_name, (old, new) in sorted(op.changes.items()):
                    out.append(f"      {field_name}: {old} → {new}")
        if self.rename_hints:
            out.append("did you mean rename (instead of delete+create)?")
            for old, new in self.rename_hints:
                out.append(f"  ? {old} -> {new}")
        if self.needs_reorder:
            out.append("reorder:")
            blockers = self.moving_unmovable()
            if blockers:
                out.append(
                    f"  ✖ blocked — role(s) can't be moved: {', '.join(blockers)}"
                )
            else:
                moved = [
                    (a, b)
                    for a, b in zip(self.current_order, self.target_order)
                    if a != b
                ]
                out.append(f"  {len(moved)} role(s) change position")
        if self.deletes:
            out.append(f"delete {len(self.deletes)} (needs --delete):")
            for op in self.deletes:
                count = (
                    f" ({op.member_count} member{'s' if op.member_count != 1 else ''})"
                    if op.member_count is not None
                    else ""
                )
                out.append(f"  - {op.name}{count}")
        elif self.strays:
            out.append(
                f"unmanaged ({len(self.strays)} strays, kept as-is): {', '.join(self.strays)}"
            )
        if self.out_of_reach:
            out.append(
                f"out of reach (above bot's highest role): {', '.join(self.out_of_reach)}"
            )
        if self.managed_skipped:
            out.append(
                f"managed (positioned only): {', '.join(self.managed_skipped)}"
            )
        if not out:
            out.append("clean — manifest matches the guild")
        return "\n".join(out)


def build_plan(
    manifest: Manifest,
    snapshot: Sequence[RoleSnapshot],
    *,
    bot_top_role_id: int | None,
    delete: bool = False,
    member_counts: Mapping[int, int] | None = None,
) -> Plan:
    """Diff the manifest against a live role snapshot."""
    live = {r["name"]: r for r in snapshot if r["name"] != EVERYONE}
    by_id = {int(r["id"]): r for r in live.values()}
    top_id = int(bot_top_role_id) if bot_top_role_id is not None else None
    top_index = _index_of(by_id.get(top_id)) if top_id in by_id else None

    # every role at or above the bot's highest role — none of these can be
    # edited; their very presence blocks any reorder permutation that would
    # move them. (The bot's own top role counts as unmovable too.)
    above_bot: list[str] = []
    for r in sorted(live.values(), key=lambda r: r["position"]):
        if top_index is None:
            break
        if r["position"] < top_index:
            above_bot.append(r["name"])

    # roles the reorder cannot move: @everyone (excluded from orders) and
    # anything at or above the bot's top role — the bot can't move roles
    # across its own highest role. Managed roles (bot, boost, shop, linked)
    # ARE movable via the API (verified empirically); they are only never
    # *edited* (see managed_skipped).
    unmovable: list[str] = [
        name
        for name, r in live.items()
        if top_index is not None and r["position"] <= top_index
    ]

    # renames: OLD->NEW lines. Perform when OLD exists and NEW doesn't.
    # When OLD is already gone, the rename is a no-op — the manifest line
    # should be cleaned up on apply (see cleanup_renames).
    rename_map: dict[str, str] = {}
    renames: list[RenameOp] = []
    conflicts: list[str] = []
    cleanup_renames: list[RenameOp] = []
    for spec in (
        role for group in manifest.groups for role in group.roles
    ):
        if spec.renamed_from is None:
            continue
        old, new = spec.renamed_from, spec.name
        rename_map[old] = new
        if old in live and new in live:
            conflicts.append(new)
        elif old in live:
            renames.append(RenameOp(old, new, spec.line))
        else:
            cleanup_renames.append(RenameOp(old, new, spec.line))

    # live roles addressed by their mapped (post-rename) name
    mapped: dict[str, RoleSnapshot] = {}
    for live_name, role in live.items():
        mapped[rename_map.get(live_name, live_name)] = role

    creates: list[CreateOp] = []
    updates: list[UpdateOp] = []
    managed_skipped: list[str] = []

    for group in manifest.groups:
        if group.title is not None:
            # the group header is a marker role: create it if missing,
            # otherwise leave it alone (it has no configurable attributes)
            marker = marker_name(group.title)
            if marker not in mapped:
                creates.append(
                    CreateOp(
                        RoleSpec(name=marker, line=group.line),
                        frozenset(),
                    )
                )
            elif mapped[marker]["managed"]:
                managed_skipped.append(marker)
        for spec in group.roles:
            role = mapped.get(spec.name)
            if role is None:
                creates.append(
                    CreateOp(spec, manifest.effective_permissions(spec))
                )
                continue
            if role["managed"]:
                managed_skipped.append(spec.name)
                continue
            if spec.name in above_bot:
                continue
            want_perms = manifest.effective_permissions(spec)
            changes = _attr_changes(spec, role, want_perms)
            if changes:
                updates.append(
                    UpdateOp(spec.name, int(role["id"]), changes)
                )

    current_order = [r["name"] for r in _ordered(snapshot)]
    mapped_order = [rename_map.get(name, name) for name in current_order]
    target_order = _target_order(manifest, mapped_order, delete)
    listed = set(manifest.ordered_names())
    strays = [
        name
        for name in current_order
        if rename_map.get(name, name) not in listed
        and not live[name]["managed"]
        and name not in above_bot
    ]

    deletes: list[DeleteOp] = []
    if delete:
        for name in strays:
            rid = int(live[name]["id"])
            deletes.append(DeleteOp(name, rid, _count(member_counts, rid)))

    return Plan(
        creates=creates,
        updates=updates,
        deletes=deletes,
        renames=renames,
        rename_conflicts=conflicts,
        rename_hints=_rename_hints(manifest, mapped, strays),
        cleanup_renames=cleanup_renames,
        current_order=mapped_order,
        target_order=target_order,
        out_of_reach=above_bot,
        managed_skipped=managed_skipped,
        strays=strays,
        unmovable=unmovable,
        top_index=top_index,
    )


def _rename_hints(
    manifest: Manifest,
    mapped: Mapping[str, RoleSnapshot],
    strays: list[str],
) -> list[tuple[str, str]]:
    """Read-only \"did you mean rename?\" suggestions.

    Fires when a manifest role is missing from the guild and an unlisted
    stray has a near-identical name — the exact delete+create pair a rename
    would avoid. Explicit ``OLD->NEW`` lines are already handled elsewhere.
    """
    hints: list[tuple[str, str]] = []
    for spec in (
        role for group in manifest.groups for role in group.roles
    ):
        if spec.renamed_from is not None or spec.name in mapped:
            continue
        best: tuple[float, str] | None = None
        for stray in strays:
            ratio = difflib.SequenceMatcher(None, stray, spec.name).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, stray)
        if best is not None and best[0] >= RENAME_HINT_RATIO:
            hints.append((best[1], spec.name))
    return hints


def _describe(spec: RoleSpec) -> str:
    """Re-render a role's manifest tokens for the diff output."""
    tokens: list[str] = []
    if spec.color:
        tokens.append(spec.color)
    if spec.hoist:
        tokens.append("hoist")
    if spec.mentionable:
        tokens.append("mentionable")
    if spec.preset:
        tokens.append(f"preset:{spec.preset}")
    tokens.extend(f"+{f}" for f in sorted(spec.grants))
    tokens.extend(f"-{f}" for f in sorted(spec.revokes))
    return f" : {' '.join(tokens)}" if tokens else ""


def _ordered(
    snapshot: Sequence[RoleSnapshot],
) -> list[RoleSnapshot]:
    return [
        r
        for r in sorted(snapshot, key=lambda r: r["position"])
        if r["name"] != EVERYONE
    ]


def _index_of(role: RoleSnapshot | None) -> int | None:
    return role["position"] if role is not None else None


def _target_order(
    manifest: Manifest,
    current_order: list[str],
    delete: bool,
) -> list[str]:
    """Manifest roles in order, then unlisted roles (bottom, current order).

    With ``delete`` the unlisted roles are left out of the target order —
    they become deletion candidates instead.
    """
    listed = list(manifest.ordered_names())
    unlisted = (
        [name for name in current_order if name not in listed]
        if not delete
        else []
    )
    return listed + unlisted


def _count(
    member_counts: Mapping[int, int] | None, rid: int
) -> int | None:
    if member_counts is None:
        return None
    return member_counts.get(rid)


def _attr_changes(
    spec: RoleSpec,
    role: RoleSnapshot,
    want_perms: frozenset[str],
) -> dict[str, tuple[Any, Any]]:
    changes: dict[str, tuple[Any, Any]] = {}

    want_color = (spec.color or "").lower()
    have_color = (role.get("color") or "").lower()
    if want_color != have_color:
        changes["color"] = (have_color or None, want_color or None)

    want_hoist = spec.hoist
    if role.get("hoisted") != want_hoist:
        changes["hoist"] = (role.get("hoisted"), want_hoist)

    if role.get("mentionable") != spec.mentionable:
        changes["mentionable"] = (
            role.get("mentionable"),
            spec.mentionable,
        )

    # icon: snapshot may not carry it; only compare when present. Asset
    # icons (https URLs) can't be set via display_icon, so they never drift
    live_icon = role.get("icon")
    if (
        "icon" in role
        and spec.icon != live_icon
        and not (
            spec.icon is None
            and live_icon
            and str(live_icon).startswith("http")
        )
    ):
        changes["icon"] = (live_icon, spec.icon)

    have_perms = set(role.get("permissions") or ())
    if have_perms != set(want_perms):
        changes["permissions"] = (
            sorted(have_perms),
            sorted(want_perms),
        )

    return changes
