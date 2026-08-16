"""Plan plumbing shared by the roles/channels diff engines.

The two engines build different Plan shapes (roles: a sidebar order;
channels: a per-block layout), so the plans themselves stay per-domain —
but the update/rename op dataclasses, the "did you mean rename?" hints
and the rename/update/hint blocks of the diff output are identical.
Keeping them here means the two renderers can't drift apart again.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# similarity ratio at which a missing item + unlisted stray get a
# "did you mean rename?" hint in the diff output
RENAME_HINT_RATIO = 0.8


@dataclass(frozen=True, slots=True)
class UpdateOp:
    name: str
    id: int
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RenameOp:
    """Rename the live item ``old`` to ``new`` (from an ``OLD->NEW`` line)."""

    old: str
    new: str
    line: int


def rename_hints(
    specs: Iterable[Any],
    mapped: Mapping[str, Any],
    strays: list[str],
) -> list[tuple[str, str]]:
    """Read-only "did you mean rename?" suggestions.

    Fires when a manifest item is missing from the guild and an unlisted
    stray has a near-identical name — the exact delete+create pair a
    rename would avoid. Explicit ``OLD->NEW`` lines are already handled
    elsewhere. ``specs`` yields the in-scope manifest specs (with
    ``renamed_from``/``name``); ``mapped`` holds the live items by
    (post-rename) name.
    """
    hints: list[tuple[str, str]] = []
    for spec in specs:
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


def render_rename_blocks(
    out: list[str],
    *,
    renames: Sequence[RenameOp],
    cleanup_renames: Sequence[RenameOp],
    conflicts: Sequence[str],
) -> None:
    """The rename / cleanup / conflict blocks of the diff output."""
    if renames:
        out.append(f"rename {len(renames)}:")
        for op in renames:
            out.append(f"  ⇄ {op.old} -> {op.new}")
    if cleanup_renames:
        out.append(
            f"cleanup {len(cleanup_renames)} (rename already applied — manifest line rewritten on apply):"
        )
        for op in cleanup_renames:
            out.append(f"  ⇄ {op.old} -> {op.new}")
    if conflicts:
        out.append("rename conflicts (new name already exists):")
        for name in conflicts:
            out.append(f"  ✖ {name}")


def render_updates(out: list[str], updates: Sequence[UpdateOp]) -> None:
    """The update block of the diff output."""
    if updates:
        out.append(f"update {len(updates)}:")
        for op in updates:
            out.append(f"  ~ {op.name}")
            for field_name, (old, new) in sorted(op.changes.items()):
                out.append(f"      {field_name}: {old} → {new}")


def render_hints(out: list[str], hints: Sequence[tuple[str, str]]) -> None:
    """The "did you mean rename?" block of the diff output."""
    if hints:
        out.append("did you mean rename (instead of delete+create)?")
        for old, new in hints:
            out.append(f"  ? {old} -> {new}")


# -- plan status -------------------------------------------------------------
#
# Both domain Plans share the same status semantics; these duck-typed
# helpers read the fields off either Plan (``getattr`` defaults cover the
# channels-only type_changes/out_of_scope and roles-only out_of_reach).


def plan_is_clean(plan: Any) -> bool:
    """True when the plan requires no changes to the guild."""
    return not (
        plan.creates
        or plan.updates
        or plan.deletes
        or plan.renames
        or plan.rename_conflicts
        or plan.cleanup_renames
        or plan.needs_reorder
        or getattr(plan, "type_changes", ())
    )


def plan_needs_apply(plan: Any) -> bool:
    """True when applying would mutate the guild (excludes manifest
    cleanup — stale rename lines are fixed by the file rewrite)."""
    return bool(
        plan.creates
        or plan.updates
        or plan.deletes
        or plan.renames
        or plan.rename_conflicts
        or plan.needs_reorder
    )


def plan_summary(plan: Any) -> str:
    """One-line drift summary for CLI output."""
    bits = [
        f"create {len(plan.creates)}",
        f"update {len(plan.updates)}",
        f"rename {len(plan.renames)}",
        "reorder" if plan.needs_reorder else "order ok",
        f"delete {len(plan.deletes)}",
    ]
    if plan.cleanup_renames:
        bits.append(f"cleanup {len(plan.cleanup_renames)}")
    if plan.rename_conflicts:
        bits.append(f"{len(plan.rename_conflicts)} rename conflicts")
    type_changes = getattr(plan, "type_changes", ())
    if type_changes:
        bits.append(f"{len(type_changes)} unsupported type changes")
    out_of_reach = getattr(plan, "out_of_reach", ())
    if out_of_reach:
        bits.append(f"{len(out_of_reach)} out of reach")
    out_of_scope = getattr(plan, "out_of_scope", ())
    if out_of_scope:
        bits.append(f"{len(out_of_scope)} out of scope")
    return " · ".join(bits)
