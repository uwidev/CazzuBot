"""Diff engine: manifest vs live guild channel snapshot → executable plan.

Turns a parsed :class:`Manifest` and a channel snapshot (plain dicts, the
shape produced by ``cazzubot.channels.executor.snapshot_guild``) into a
:class:`Plan` of creates / updates / renames / deletes plus the target
layout. Pure and offline-testable — the snapshot is plain dicts, not
discord objects.

Scope: with ``scope_below=<category name>`` only the groups from that
category downward (in manifest order) are managed; everything above is
reported as out of scope and never touched — the mechanism for running the
engine against the bottom of a busy guild.

Layout model: Discord keeps two independent position spaces per parent —
the text section (text / announcement / forum channels) and the voice
section (voice / stage channels); categories have their own space. The
manifest order within a category therefore only matters within each
section, and ``needs_reorder`` compares per ``(category, section)`` block.

Kinds: a live channel whose kind differs from the manifest is an update
when it's the supported text<->announcement conversion, otherwise a
reported type change (never applied).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cazzubot.channels.parser import ChannelSpec, Manifest
from cazzubot.channels.snapshot import (
    ChannelSnapshot,
    SLOWMODE_KINDS,
    VOICE_KINDS,
)
from cazzubot.manifest.plan import (
    RenameOp,
    UpdateOp,
    plan_is_clean,
    plan_needs_apply,
    plan_summary,
    rename_hints,
    render_hints,
    render_rename_blocks,
    render_updates,
)

# the position sections Discord keeps per parent
BUCKET_TEXT = "text"
BUCKET_VOICE = "voice"
BUCKET_CATEGORY = "category"

# kinds that can convert into each other via the edit API (Discord only
# supports text <-> announcement conversion)
CONVERTIBLE = frozenset({"text", "announcement"})


def bucket_of(kind: str) -> str:
    """The bucket a channel ``kind`` sorts into: category/voice/text."""
    if kind == "category":
        return BUCKET_CATEGORY
    if kind in ("voice", "stage"):
        return BUCKET_VOICE
    return BUCKET_TEXT


@dataclass(frozen=True, slots=True)
class CreateOp:
    """Plan op: create one channel with its parent ``category``."""

    spec: ChannelSpec
    category: str | None


@dataclass(frozen=True, slots=True)
class DeleteOp:
    """Plan op: delete the channel identified by ``name`` and ``id``."""

    name: str
    id: int


@dataclass(frozen=True, slots=True)
class Plan:
    """The full set of changes the manifest implies (in-scope only)."""

    creates: list[CreateOp]
    updates: list[UpdateOp]
    deletes: list[DeleteOp]
    renames: list[RenameOp]
    rename_conflicts: list[str]
    rename_hints: list[tuple[str, str]]
    cleanup_renames: list[RenameOp]
    layout: dict[tuple[str | None, str], list[str]]  # current per block
    target: dict[tuple[str | None, str], list[str]]  # desired per block
    type_changes: list[str]
    out_of_scope: list[str]
    unsupported: list[str]
    strays: list[str]
    stray_categories: list[str]
    in_scope_ids: tuple[int, ...]

    @property
    def needs_reorder(self) -> bool:
        """True when the desired layout differs from the current one."""
        return self.layout != self.target

    def is_clean(self) -> bool:
        """True when the plan requires no changes to the guild."""
        return plan_is_clean(self)

    @property
    def needs_apply(self) -> bool:
        """Anything that requires mutating the guild (excludes manifest
        cleanup — stale rename lines are fixed by the file rewrite)."""
        return plan_needs_apply(self)

    def summary(self) -> str:
        """A one-line human-readable summary of the plan."""
        return plan_summary(self)

    def render(self) -> str:
        """Human-readable diff for the terminal / boot log."""
        out: list[str] = []
        render_rename_blocks(
            out,
            renames=self.renames,
            cleanup_renames=self.cleanup_renames,
            conflicts=self.rename_conflicts,
        )
        if self.creates:
            out.append(f"create {len(self.creates)}:")
            for op in self.creates:
                cat = (
                    f" → {op.category}"
                    if op.category
                    else " (uncategorized)"
                )
                out.append(f"  + {op.spec.name}{cat}{_describe(op.spec)}")
        render_updates(out, self.updates)
        render_hints(out, self.rename_hints)
        if self.needs_reorder:
            out.append("reorder:")
            for block in sorted(
                self.target,
                key=lambda k: (k[0] is not None, k[0] or "", k[1]),
            ):
                key, want = block, self.target[block]
                have = self.layout.get(key, [])
                if have == want:
                    continue
                where, section = key
                label = f"{where or '(uncategorized)'} [{section}]"
                out.append(
                    f"  ~ {label}: {', '.join(have)} → {', '.join(want)}"
                )
        if self.type_changes:
            out.append(
                "unsupported type changes (delete+recreate manually to fix):"
            )
            for name in self.type_changes:
                out.append(f"  ✖ {name}")
        if self.deletes:
            out.append(f"delete {len(self.deletes)} (needs --delete):")
            for op in self.deletes:
                out.append(f"  - {op.name}")
        elif self.strays:
            out.append(
                f"unmanaged ({len(self.strays)} strays, kept as-is): {', '.join(self.strays)}"
            )
        if self.stray_categories:
            out.append(
                f"stray categories (kept; deleted with --delete only when empty): "
                f"{', '.join(self.stray_categories)}"
            )
        if self.unsupported:
            out.append(
                f"unsupported kinds (kept as-is): {', '.join(self.unsupported)}"
            )
        if self.out_of_scope:
            out.append(
                f"out of scope (kept as-is): {len(self.out_of_scope)} channel(s)"
            )
        if not out:
            out.append("clean — manifest matches the guild")
        return "\n".join(out)


def build_plan(
    manifest: Manifest,
    snapshot: Sequence[ChannelSnapshot],
    *,
    scope_below: str | None = None,
    delete: bool = False,
) -> Plan:
    """Diff the manifest against a live channel snapshot.

    ``scope_below`` limits management to the manifest group with that
    title and everything after it; groups above are out of scope.
    """
    titles = manifest.titles()  # tuple: indexable, ordered
    boundary = 0
    if scope_below is not None:
        try:
            boundary = titles.index(scope_below)
        except ValueError:
            raise ValueError(
                f"scope group {scope_below!r} not found in the manifest — "
                "use the exact [header] title"
            ) from None
    out_of_scope = _names_of(manifest, range(boundary))

    in_scope_cats = {
        group.title
        for group in manifest.groups[boundary:]
        if group.title is not None
    }

    def in_scope(ch: ChannelSnapshot) -> bool:
        """True when a live channel belongs to the managed region.

        With a scope boundary, only channels inside an in-scope category
        are managed — uncategorized channels render above every category,
        so they are out of scope too. The in-scope category channels
        themselves (which have no parent) count as in scope by name.
        """
        if boundary == 0:
            return True
        if ch["category"] in in_scope_cats:
            return True
        return ch["kind"] == "category" and ch["name"] in in_scope_cats

    # first occurrence wins — later duplicates are marked unsupported by
    # the snapshot and must not hijack the name-keyed matching. With a
    # scope boundary, out-of-scope channels are excluded entirely so a
    # name collision can never make the plan touch them.
    live: dict[str, ChannelSnapshot] = {}
    for ch in snapshot:
        if not in_scope(ch):
            continue
        live.setdefault(ch["name"], ch)

    # manifest names in the managed region (titles + channels)
    listed = set(
        _names_of(manifest, range(boundary, len(manifest.groups)))
    )
    # names addressed by plain lines (not rename targets) — only these
    # make a rename a conflict: renaming onto a name held solely by an
    # unlisted stray or duplicate is safe, the duplicate handling takes
    # over
    plain_names = set()
    for group in manifest.groups[boundary:]:
        if group.title is not None:
            plain_names.add(group.title)
        for spec in group.channels:
            if spec.renamed_from is None:
                plain_names.add(spec.name)

    # renames: OLD->NEW lines, in-scope groups only
    rename_map: dict[str, str] = {}
    renames: list[RenameOp] = []
    conflicts: list[str] = []
    cleanup_renames: list[RenameOp] = []
    for group in manifest.groups[boundary:]:
        for spec in group.channels:
            if spec.renamed_from is None:
                continue
            old, new = spec.renamed_from, spec.name
            rename_map[old] = new
            if old in live and new in live and new in plain_names:
                conflicts.append(new)
            elif old in live:
                renames.append(RenameOp(old, new, spec.line))
            else:
                cleanup_renames.append(RenameOp(old, new, spec.line))

    # live channels addressed by their mapped (post-rename) name. First
    # occurrence in snapshot order wins — when a rename target collides
    # with an existing channel name, the earlier channel is the managed
    # one and the later becomes an unmanaged duplicate.
    mapped: dict[str, ChannelSnapshot] = {}
    for ch in snapshot:
        if not in_scope(ch):
            continue
        mapped.setdefault(rename_map.get(ch["name"], ch["name"]), ch)

    creates: list[CreateOp] = []
    updates: list[UpdateOp] = []
    type_changes: list[str] = []
    unsupported: list[str] = []

    for group in manifest.groups[boundary:]:
        if group.title is not None:
            if group.title not in mapped:
                creates.append(
                    CreateOp(
                        ChannelSpec(
                            name=group.title,
                            line=group.line,
                            kind="category",
                        ),
                        None,
                    )
                )
            elif mapped[group.title].get("unsupported"):
                unsupported.append(group.title)
            elif mapped[group.title]["kind"] != "category":
                # the title's name is held by a non-category channel —
                # Discord names are guild-unique, so the category can't
                # exist under this name; block apply instead of
                # misplacing children
                type_changes.append(group.title)
        for spec in group.channels:
            ch = mapped.get(spec.name)
            if ch is None:
                creates.append(CreateOp(spec, group.title))
                continue
            if ch.get("unsupported"):
                unsupported.append(spec.name)
                continue
            if ch["kind"] != spec.kind:
                if {ch["kind"], spec.kind} <= CONVERTIBLE:
                    updates.append(
                        UpdateOp(
                            spec.name,
                            int(ch["id"]),
                            {"kind": (ch["kind"], spec.kind)},
                        )
                    )
                else:
                    type_changes.append(spec.name)
                continue
            changes = _attr_changes(spec, ch)
            if changes:
                updates.append(UpdateOp(spec.name, int(ch["id"]), changes))

    # any live channel the engine can't address by name (duplicates) or
    # kind is reported and kept as-is (in-scope only — out-of-scope
    # channels are simply not managed)
    unsupported.extend(
        ch["name"]
        for ch in snapshot
        if ch.get("unsupported") and in_scope(ch)
    )
    unsupported = list(dict.fromkeys(unsupported))

    layout = _live_layout(snapshot, listed, rename_map, in_scope)
    # names whose only live occurrences are unsupported (duplicates of
    # unlisted channels, unrepresentable names) are excluded from the
    # target so they can't cause a permanent reorder drift; names that
    # also have a managed occurrence stay addressable
    unsupported_names = {
        ch["name"]
        for ch in snapshot
        if ch.get("unsupported") and in_scope(ch)
    } - {
        ch["name"]
        for ch in snapshot
        if not ch.get("unsupported") and in_scope(ch)
    }
    target = _target_layout(manifest, boundary, unsupported_names)

    # ids of the in-scope managed channels the manifest addresses — the
    # executor resolves target names against exactly this set so the
    # reorder can never grab an out-of-scope channel with a colliding
    # name
    in_scope_ids = tuple(
        int(ch["id"])
        for name in sorted(listed)
        if (ch := mapped.get(name)) is not None
        and not ch.get("unsupported")
        and in_scope(ch)
    )

    # manifest names declared above the scope boundary stay out of the
    # stray/delete sets even when the channel physically sits inside an
    # in-scope category — the manifest still governs it
    out_scope_names = set(out_of_scope)
    strays = [
        ch["name"]
        for ch in snapshot
        if in_scope(ch)
        and ch["name"] not in listed
        and ch["name"] not in out_scope_names
        and ch["name"] not in rename_map
        and not ch.get("unsupported")
        and ch["kind"] != "category"
    ]
    stray_categories = [
        ch["name"]
        for ch in snapshot
        if in_scope(ch)
        and ch["kind"] == "category"
        and not ch.get("unsupported")
        and ch["name"] not in listed
        and ch["name"] not in out_scope_names
    ]

    deletes: list[DeleteOp] = []
    if delete:
        # ids come from the stray entries themselves (supported,
        # in-scope) — never from an unsupported first occurrence sharing
        # the name
        stray_ids = {
            ch["name"]: int(ch["id"])
            for ch in snapshot
            if in_scope(ch)
            and ch["name"] in set(strays)
            and not ch.get("unsupported")
        }
        for name in strays:
            deletes.append(DeleteOp(name, stray_ids[name]))
        # a stray category may be deleted only while empty — deleting a
        # category with children would cascade-delete them
        child_cats = {ch["category"] for ch in snapshot}
        # ids come from the supported entries themselves, like stray_ids
        stray_cat_ids = {
            ch["name"]: int(ch["id"])
            for ch in snapshot
            if in_scope(ch)
            and ch["name"] in set(stray_categories)
            and not ch.get("unsupported")
        }
        for name in stray_categories:
            if name not in child_cats:
                deletes.append(DeleteOp(name, stray_cat_ids[name]))

    return Plan(
        creates=creates,
        updates=updates,
        deletes=deletes,
        renames=renames,
        rename_conflicts=conflicts,
        rename_hints=rename_hints(
            (
                spec
                for group in manifest.groups[boundary:]
                for spec in group.channels
            ),
            mapped,
            strays,
        ),
        cleanup_renames=cleanup_renames,
        layout=layout,
        target=target,
        type_changes=type_changes,
        out_of_scope=out_of_scope,
        unsupported=unsupported,
        strays=strays,
        stray_categories=stray_categories,
        in_scope_ids=in_scope_ids,
    )


def _names_of(
    manifest: Manifest, group_indices: Sequence[int]
) -> list[str]:
    """Ordered names (category titles + channels) of the given groups."""
    names: list[str] = []
    for idx in group_indices:
        group = manifest.groups[idx]
        if group.title is not None:
            names.append(group.title)
        names.extend(ch.name for ch in group.channels)
    return names


def _attr_changes(
    spec: ChannelSpec, ch: ChannelSnapshot
) -> dict[str, tuple[Any, Any]]:
    changes: dict[str, tuple[Any, Any]] = {}
    # only non-category specs reach here (categories are the title branch)
    if ch["nsfw"] != spec.nsfw:
        changes["nsfw"] = (ch["nsfw"], spec.nsfw)
    if spec.kind in SLOWMODE_KINDS:
        if ch["slowmode"] != spec.slowmode:
            changes["slowmode"] = (ch["slowmode"], spec.slowmode)
    if spec.kind in VOICE_KINDS:
        # absence means the Discord default: 64 kbps, unlimited, auto
        want_bitrate = spec.bitrate if spec.bitrate is not None else 64
        if ch.get("bitrate") != want_bitrate:
            changes["bitrate"] = (ch.get("bitrate"), want_bitrate)
        want_limit = spec.limit if spec.limit is not None else 0
        have_limit = ch.get("limit") or 0
        if have_limit != want_limit:
            changes["limit"] = (have_limit, want_limit)
        want_region = (
            None if spec.region in (None, "auto") else spec.region
        )
        if ch.get("region") != want_region:
            changes["region"] = (ch.get("region"), want_region)
        want_quality = "auto" if spec.quality is None else spec.quality
        if ch.get("quality") != want_quality:
            changes["quality"] = (ch.get("quality"), want_quality)
    return changes


def _live_layout(
    snapshot: Sequence[ChannelSnapshot],
    listed: set[str],
    rename_map: Mapping[str, str],
    in_scope: Callable[[ChannelSnapshot], bool],
) -> dict[tuple[str | None, str], list[str]]:
    """Live layout of listed channels, per (parent category, section).

    Strays and out-of-scope channels are excluded — they are kept as-is
    and must not make the plan report a reorder forever. Channels
    renamed by ``OLD->NEW`` lines are addressed under their new name.
    Categories sort in their own section under the uncategorized key
    (they have no parent).
    """
    blocks: dict[tuple[str | None, str], list[ChannelSnapshot]] = {}
    seen_names: set[str] = set()
    for ch in snapshot:
        if ch.get("unsupported") or not in_scope(ch):
            continue
        name = rename_map.get(ch["name"], ch["name"])
        if name in seen_names:
            continue  # duplicate occurrence — never managed
        seen_names.add(name)
        if name not in listed:
            continue
        key = (ch["category"], bucket_of(ch["kind"]))
        blocks.setdefault(key, []).append(ch)
    return {
        key: [
            rename_map.get(ch["name"], ch["name"])
            for ch in sorted(group, key=lambda c: c["position"])
        ]
        for key, group in blocks.items()
    }


def _target_layout(
    manifest: Manifest,
    boundary: int,
    unsupported_names: set[str],
) -> dict[tuple[str | None, str], list[str]]:
    """Manifest layout, per (category, section), in-scope groups.

    Channels the live guild can't manage (duplicates, unrepresentable
    names) are excluded so they can't cause a permanent reorder drift.
    """
    blocks: dict[tuple[str | None, str], list[str]] = {}
    for group in manifest.groups[boundary:]:
        for spec in group.channels:
            if spec.name in unsupported_names:
                continue
            key = (group.title, bucket_of(spec.kind))
            blocks.setdefault(key, []).append(spec.name)
    categories = [
        group.title
        for group in manifest.groups[boundary:]
        if group.title is not None and group.title not in unsupported_names
    ]
    if categories:
        blocks[(None, BUCKET_CATEGORY)] = categories
    return blocks




def _describe(spec: ChannelSpec) -> str:
    """Re-render a channel's manifest tokens for the diff output."""
    tokens: list[str] = []
    if spec.kind != "text":
        tokens.append(f"type:{spec.kind}")
    if spec.nsfw:
        tokens.append("nsfw")
    if spec.slowmode:
        tokens.append(f"slowmode:{spec.slowmode}")
    if spec.bitrate is not None:
        tokens.append(f"bitrate:{spec.bitrate}")
    if spec.limit is not None:
        tokens.append(f"limit:{spec.limit}")
    if spec.region:
        tokens.append(f"region:{spec.region}")
    if spec.quality:
        tokens.append(f"quality:{spec.quality}")
    return f" : {' '.join(tokens)}" if tokens else ""
