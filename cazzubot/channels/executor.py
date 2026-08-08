"""Live executor: apply a :class:`Plan` against a real guild.

Bridges the pure parser/plan engine to discord: snapshots a guild into the
same dict shape the engine consumes, applies a plan (rename → create →
update → delete → reorder), and supports snapshot-based backups and
restores.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord
import pendulum

from cazzubot.channels.export import QUALITY_VALUES
from cazzubot.channels.parser import (
    ChannelSpec,
    parse,
)
from cazzubot.channels.plan import (
    Plan,
    RenameOp,
    bucket_of,
)
from cazzubot.channels.snapshot import (
    ChannelSnapshot,
    SLOWMODE_KINDS,
    VOICE_KINDS,
)
from discord.abc import GuildChannel

REORDER_ATTEMPTS = 5

CHANNEL_TYPE = {
    "text": discord.ChannelType.text,
    "announcement": discord.ChannelType.news,
    "voice": discord.ChannelType.voice,
    "forum": discord.ChannelType.forum,
    "stage": discord.ChannelType.stage_voice,
    "category": discord.ChannelType.category,
}


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Outcome of an apply: errors plus the renames that actually ran."""

    errors: list[str]
    applied_renames: list[RenameOp]


# -- snapshots ---------------------------------------------------------------


async def snapshot_guild(guild: discord.Guild) -> list[ChannelSnapshot]:
    """The guild's channels as plain dicts, from a fresh API fetch.

    Discord allows duplicate channel names; the engine keys channels by
    name, so every channel after the first with a given name is marked
    ``unsupported`` — it is kept as-is and never managed.
    """
    channels = await guild.fetch_channels()
    cats = {
        ch.id: ch.name
        for ch in channels
        if isinstance(ch, discord.CategoryChannel)
    }
    # duplicate (non-first) categories are unmanaged; channels inside
    # them are unaddressable by name too — mark them unsupported so they
    # can never be matched, reordered or deleted
    seen_cats: set[str] = set()
    dup_cat_ids: set[int] = set()
    for ch in channels:
        if isinstance(ch, discord.CategoryChannel):
            if ch.name in seen_cats:
                dup_cat_ids.add(ch.id)
            seen_cats.add(ch.name)
    out: list[ChannelSnapshot] = []
    seen: set[str] = set()
    for ch in channels:
        kind, unsupported = _kind_of(ch)
        category = (
            cats[ch.category_id]
            if ch.category_id is not None and ch.category_id in cats
            else None
        )
        snap = _snapshot_channel(ch, kind, category)
        if (
            unsupported
            or ch.name in seen
            or not _representable_name(ch.name)
            or (
                ch.category_id is not None
                and ch.category_id in dup_cat_ids
            )
        ):
            snap["unsupported"] = True
        seen.add(ch.name)
        out.append(snap)
    return out


def _representable_name(name: str) -> bool:
    """True when a channel name round-trips through the manifest format.

    Mirrors the parser's line grammar: names containing ``->`` (rename
    syntax) or `` : `` (token separator), names ending with `` :`` (the
    parser's trailing-separator branch), names with leading/trailing
    whitespace, names starting with ``[`` (header syntax) or ``#``
    (comment syntax), and whitespace-only names can't be written
    verbatim and re-parsed — such channels are kept as-is.
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


def _kind_of(ch: GuildChannel) -> tuple[str, bool]:
    """(kind, unsupported) for a live channel object."""
    if isinstance(ch, discord.CategoryChannel):
        return "category", False
    if isinstance(ch, discord.StageChannel):
        return "stage", False
    if isinstance(ch, discord.VoiceChannel):
        return "voice", False
    if isinstance(ch, discord.ForumChannel):
        return "forum", False
    if isinstance(ch, discord.TextChannel):
        if ch.type == discord.ChannelType.news:
            return "announcement", False
        return "text", False
    return ch.type.name, True


def _snapshot_channel(
    ch: GuildChannel, kind: str, category: str | None
) -> ChannelSnapshot:
    snap: ChannelSnapshot = {
        "id": str(ch.id),
        "name": ch.name,
        "kind": kind,
        "category": category,
        "position": ch.position,
        "nsfw": bool(getattr(ch, "nsfw", False)),
        "slowmode": 0,
    }
    if kind in SLOWMODE_KINDS:
        snap["slowmode"] = int(
            getattr(ch, "slowmode_delay", 0)
            or getattr(ch, "default_thread_slowmode_delay", 0)
            or 0
        )
    if kind in VOICE_KINDS:
        snap["bitrate"] = int(getattr(ch, "bitrate", 0) or 0) // 1000
        snap["limit"] = int(getattr(ch, "user_limit", 0) or 0)
        snap["region"] = getattr(ch, "rtc_region", None)
        vqm = getattr(ch, "video_quality_mode", None)
        # server values: 1=auto, 2=1080
        raw = str(vqm.value) if vqm is not None else None
        snap["quality"] = {"1": "auto", "2": "1080"}.get(raw, raw)
    return snap


def save_snapshot(path: Path, channels: list[ChannelSnapshot]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(channels, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_snapshot(path: Path) -> list[ChannelSnapshot]:
    return json.loads(path.read_text(encoding="utf-8"))


def backup_path(base: Path) -> Path:
    """``<base>/channels-YYYYMMDD-HHMMSS.json`` in UTC."""
    stamp = pendulum.now("UTC").format("YYYYMMDD-HHMMSS")
    return base / f"channels-{stamp}.json"


# -- applying ----------------------------------------------------------------


async def apply_plan(
    guild: discord.Guild, plan: Plan, *, delete: bool
) -> ApplyResult:
    """Execute a plan, returning errors plus the renames that ran.

    One authoritative fresh channel view is threaded through the whole
    apply: lookups for the next operation use the verified state after
    the previous one. The local cache is never read — it lags the gateway.
    """
    errors: list[str] = []
    applied_renames: list[RenameOp] = []
    reason = "channels manifest apply"

    async def refresh() -> list[GuildChannel]:
        return await guild.fetch_channels()

    current = await refresh()

    # 0. renames first — later steps match channels under their new names.
    # The lookup is restricted to the plan's in-scope set so a colliding
    # out-of-scope channel can never be renamed.
    for op in plan.renames:
        channel = next(
            (
                c
                for c in current
                if c.id in plan.in_scope_ids and c.name == op.old
            ),
            None,
        )
        if channel is None:
            errors.append(f"rename {op.old}: channel not found")
            continue
        try:
            await channel.edit(name=op.new, reason=reason)
        except discord.HTTPException as err:
            errors.append(f"rename {op.old}: {err}")
            continue
        current = await refresh()
        names = {c.name for c in current}
        if op.new not in names:
            errors.append(
                f"rename {op.old}: did not take effect (verification)"
            )
        else:
            applied_renames.append(op)

    # 1. creates (categories first, so children can reference them)
    cat_ids = _category_ids(current, set(plan.in_scope_ids))
    for op in plan.creates:
        if op.spec.kind == "category":
            try:
                await guild.create_category(op.spec.name, reason=reason)
            except discord.HTTPException as err:
                errors.append(f"create {op.spec.name}: {err}")
                continue
            current = await refresh()
            cat_ids = _category_ids(current, set(plan.in_scope_ids))
            if op.spec.name not in cat_ids:
                errors.append(
                    f"create {op.spec.name}: not present after verification"
                )
            continue
        parent = (
            cat_ids.get(op.category) if op.category is not None else None
        )
        try:
            await _create_channel(guild, op.spec, parent, reason=reason)
        except discord.HTTPException as err:
            errors.append(f"create {op.spec.name}: {err}")
            continue
        current = await refresh()
        if op.spec.name not in {c.name for c in current}:
            errors.append(
                f"create {op.spec.name}: not present after verification"
            )

    # 2. updates
    by_id = {c.id: c for c in current}
    for op in plan.updates:
        channel = by_id.get(op.id)
        if channel is None:
            errors.append(f"update {op.name}: channel not found")
            continue
        try:
            await _edit_channel(channel, op.changes, reason)
        except discord.HTTPException as err:
            errors.append(f"update {op.name}: {err}")
            continue
        current = await refresh()
        verified = next((c for c in current if c.id == op.id), None)
        if verified is None:
            errors.append(f"update {op.name}: channel vanished after edit")
        else:
            mismatches = _attr_mismatches(verified, op.changes)
            if mismatches:
                errors.append(
                    f"update {op.name}: {', '.join(mismatches)} did not take effect (verification)"
                )

    # 3. deletes
    if delete:
        for op in plan.deletes:
            channel = next((c for c in current if c.id == op.id), None)
            if channel is None:
                continue
            if isinstance(channel, discord.CategoryChannel):
                # re-verify the category is still childless right before
                # deleting — a channel created in it since the plan was
                # built would otherwise be cascade-deleted
                if any(
                    c.category_id == op.id
                    for c in current
                    if c.id != op.id
                ):
                    errors.append(
                        f"delete {op.name}: category gained children since "
                        "the plan — skipping"
                    )
                    continue
            try:
                await channel.delete(reason=reason)
            except discord.HTTPException as err:
                errors.append(f"delete {op.name}: {err}")
                continue
            current = await refresh()
            if any(c.id == op.id for c in current):
                errors.append(
                    f"delete {op.name}: still present after verification"
                )

    # 4. reorder (never partially applied — one bulk PATCH, converges)
    if plan.needs_reorder:
        try:
            await reorder_guild(guild, plan.target, plan.in_scope_ids)
        except (discord.HTTPException, RuntimeError) as err:
            errors.append(f"reorder: {err}")

    return ApplyResult(errors=errors, applied_renames=applied_renames)


async def _create_channel(
    guild: discord.Guild,
    spec: ChannelSpec,
    parent_id: int | None,
    *,
    reason: str,
) -> None:
    """Create a channel via the low-level HTTP client.

    Deliberately bypasses the high-level ``guild.create_*`` helpers: they
    resolve the parent category through the local cache, which lags the
    gateway after a category was just created in the same apply. The REST
    endpoint takes the same payload keys and returns the created channel.
    """
    payload: dict[str, Any] = {"name": spec.name}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    if spec.kind in ("text", "announcement", "forum", "voice", "stage"):
        if spec.nsfw:
            payload["nsfw"] = True
    if spec.kind in SLOWMODE_KINDS and spec.slowmode:
        if spec.kind == "forum":
            payload["default_thread_rate_limit_per_user"] = spec.slowmode
        else:
            payload["rate_limit_per_user"] = spec.slowmode
    if spec.kind in VOICE_KINDS:
        if spec.bitrate is not None:
            payload["bitrate"] = spec.bitrate * 1000
        if spec.limit is not None:
            payload["user_limit"] = spec.limit
        if spec.region is not None:
            payload["rtc_region"] = (
                None if spec.region == "auto" else spec.region
            )
        if spec.quality is not None:
            payload["video_quality_mode"] = QUALITY_VALUES[spec.quality]
    await guild._state.http.create_channel(
        guild.id,
        CHANNEL_TYPE[spec.kind].value,
        reason=reason,
        **payload,
    )


def _vqm(label: str) -> discord.VideoQualityMode:
    return discord.VideoQualityMode(QUALITY_VALUES[label])


async def _edit_channel(
    channel: GuildChannel,
    changes: dict[str, tuple[Any, Any]],
    reason: str,
) -> None:
    kwargs: dict[str, Any] = {}
    for field_name, (_, new) in changes.items():
        if field_name == "kind":
            kwargs["type"] = (
                discord.ChannelType.news
                if new == "announcement"
                else discord.ChannelType.text
            )
        elif field_name == "nsfw":
            kwargs["nsfw"] = new
        elif field_name == "slowmode":
            if isinstance(channel, discord.ForumChannel):
                kwargs["default_thread_slowmode_delay"] = new
            else:
                kwargs["slowmode_delay"] = new
        elif field_name == "bitrate":
            kwargs["bitrate"] = new * 1000
        elif field_name == "limit":
            kwargs["user_limit"] = new
        elif field_name == "region":
            kwargs["rtc_region"] = None if new == "auto" else new
        elif field_name == "quality":
            kwargs["video_quality_mode"] = _vqm(new)
    await channel.edit(**kwargs, reason=reason)


def _attr_mismatches(
    channel: GuildChannel, changes: dict[str, tuple[Any, Any]]
) -> list[str]:
    """Field names in ``changes`` that the live channel doesn't match yet."""
    out: list[str] = []
    for field_name, (_, want) in changes.items():
        if field_name == "kind":
            have = (
                "announcement"
                if getattr(channel, "type", None)
                == discord.ChannelType.news
                else "text"
            )
            if have != want:
                out.append("kind")
        elif field_name == "nsfw":
            if getattr(channel, "nsfw", False) != want:
                out.append("nsfw")
        elif field_name == "slowmode":
            if isinstance(channel, discord.ForumChannel):
                have = int(
                    getattr(channel, "default_thread_slowmode_delay", 0)
                    or 0
                )
            else:
                have = int(getattr(channel, "slowmode_delay", 0) or 0)
            if have != want:
                out.append("slowmode")
        elif field_name == "bitrate":
            if int(getattr(channel, "bitrate", 0) or 0) != want * 1000:
                out.append("bitrate")
        elif field_name == "limit":
            if int(getattr(channel, "user_limit", 0) or 0) != want:
                out.append("limit")
        elif field_name == "region":
            have = getattr(channel, "rtc_region", None)
            if have != (None if want == "auto" else want):
                out.append("region")
        elif field_name == "quality":
            vqm = getattr(channel, "video_quality_mode", None)
            have = {1: "auto", 2: "1080"}.get(
                vqm.value if vqm is not None else None
            )
            if have != want:
                out.append("quality")
    return out


# -- reorder ----------------------------------------------------------------


def _category_ids(
    channels: list[GuildChannel], managed_ids: set[int]
) -> dict[str, int]:
    """Category name → id, preferring managed (in-scope) categories.

    Discord allows duplicate category names; first occurrence wins, with
    managed ids taking precedence so a colliding out-of-scope category
    can never be the move target.
    """
    cat_ids: dict[str, int] = {}
    for c in channels:
        if isinstance(c, discord.CategoryChannel) and c.id in managed_ids:
            cat_ids.setdefault(c.name, c.id)
    for c in channels:
        if isinstance(c, discord.CategoryChannel):
            cat_ids.setdefault(c.name, c.id)
    return cat_ids


async def reorder_guild(
    guild: discord.Guild,
    target: dict[tuple[str | None, str], list[str]],
    managed_ids: tuple[int, ...],
) -> None:
    """Move channels so the layout matches ``target``.

    ``target`` maps ``(category name | None, section)`` to the desired
    channel-name order (see ``cazzubot.channels.plan``); ``managed_ids``
    are the in-scope channel ids the plan manages — names resolve only
    among them, so an out-of-scope channel can never be grabbed by a
    colliding name. Two kinds of change, applied separately:

    - **parent moves** — the bulk endpoint accepts at most one
      ``parent_id`` per request, so each channel changing category is
      moved with its own ``edit(category=...)`` call;
    - **positions** — the remaining reorder is one bulk PATCH per
      attempt.

    Channels are re-fetched from the API and the passes re-applied until
    the layout holds — Discord resolves moves inconsistently in a single
    payload and the gateway lags the local cache. Bounded attempts, then
    an error if it never converges.
    """
    for _ in range(REORDER_ATTEMPTS):
        parent_moves = await _parent_moves(guild, target, managed_ids)
        for channel, parent_id in parent_moves:
            await channel.edit(
                category=(
                    discord.Object(id=parent_id)
                    if parent_id is not None
                    else None
                ),
                reason="channels manifest apply",
            )
        payload = await _reorder_payload(guild, target, managed_ids)
        if not parent_moves and not payload:
            return
        if payload:
            await guild._state.http.bulk_channel_update(
                guild.id, payload, reason="channels manifest apply"
            )
        await asyncio.sleep(
            0.6
        )  # let the gateway settle before re-reading
    payload = await _reorder_payload(guild, target, managed_ids)
    if payload:
        raise RuntimeError(
            f"reorder did not converge after {REORDER_ATTEMPTS} attempts — "
            f"{len(payload)} move(s) remain; re-run channels apply"
        )


async def _parent_moves(
    guild: discord.Guild,
    target: dict[tuple[str | None, str], list[str]],
    managed_ids: tuple[int, ...],
) -> list[tuple[GuildChannel, int | None]]:
    """(channel, target parent id) for every channel changing category.

    Names resolve only among ``managed_ids`` (the plan's in-scope set),
    so a colliding out-of-scope name can never hijack the move.
    """
    channels = await guild.fetch_channels()
    cat_ids = _category_ids(channels, set(managed_ids))
    by_name: dict[str, GuildChannel] = {}
    for c in channels:
        if c.id in managed_ids:
            by_name.setdefault(c.name, c)

    moves: list[tuple[GuildChannel, int | None]] = []
    seen: set[int] = set()
    for (category, _section), names in target.items():
        parent_id = None if category is None else cat_ids.get(category)
        if category is not None and parent_id is None:
            raise RuntimeError(
                f"reorder: category {category!r} not found — refusing to move its channels"
            )
        for name in names:
            ch = by_name.get(name)
            if ch is None or ch.id in seen:
                continue
            if ch.category_id != parent_id:
                moves.append((ch, parent_id))
                seen.add(ch.id)
    return moves


async def _reorder_payload(
    guild: discord.Guild,
    target: dict[tuple[str | None, str], list[str]],
    managed_ids: tuple[int, ...],
) -> list[dict[str, Any]]:
    """The position-only bulk payload that moves the guild toward ``target``.

    Names resolve only among ``managed_ids`` (the plan's in-scope set),
    so duplicate-named or out-of-scope channels can never be grabbed by
    a colliding name. Parent changes are handled separately by
    :func:`_parent_moves` — the bulk endpoint accepts at most one
    ``parent_id`` per request.
    """
    channels = await guild.fetch_channels()
    cat_ids = _category_ids(channels, set(managed_ids))
    by_name: dict[str, GuildChannel] = {}
    for c in channels:
        if c.id in managed_ids:
            by_name.setdefault(c.name, c)

    payload: list[dict[str, Any]] = []
    for (category, section), names in target.items():
        parent_id = cat_ids.get(category) if category is not None else None
        if category is not None and parent_id is None:
            raise RuntimeError(
                f"reorder: category {category!r} not found — refusing to move its channels"
            )
        # the block's current members: same parent and same position
        # section (duplicates included — they reserve their slots even
        # though they are never emitted). Target-named channels living
        # elsewhere (a parent change applied moments ago, or a just-created
        # channel) are pulled in via ``by_name``.
        members = [
            c
            for c in channels
            if (
                (c.category_id == parent_id)
                if category is not None
                else c.category_id is None
            )
            and bucket_of(_kind_of(c)[0]) == section
        ]
        members.sort(key=lambda c: c.position)
        ordered_target = [by_name[n] for n in names if n in by_name]

        # anchor walk: channels not in the target keep their current slots
        # (out-of-scope channels, strays and duplicates never move);
        # target channels fill the remaining slots in manifest order,
        # extending the block when channels are arriving from elsewhere.
        # Kept channels pin their own index — with duplicate names, each
        # occurrence must pin its own slot (members.index would pin the
        # first occurrence twice).
        kept = {c.name for c in members} - set(names)
        final: list[GuildChannel | None] = [None] * len(members)
        for idx, ch in enumerate(members):
            if ch.name in kept:
                final[idx] = ch
        free = [i for i, ch in enumerate(final) if ch is None]
        cursor = 0
        for ch in ordered_target:
            if cursor < len(free):
                final[free[cursor]] = ch
            else:
                final.append(ch)
            cursor += 1

        for index, ch in enumerate(final):
            if ch is None or ch.id not in managed_ids:
                continue
            if ch.position != index:
                payload.append({"id": ch.id, "position": index})
    return payload


async def restore_guild(
    guild: discord.Guild, snapshot: list[ChannelSnapshot]
) -> list[str]:
    """Bring the guild back toward a snapshot (never deletes anything)."""
    from cazzubot.channels.export import render_manifest

    manifest = parse(render_manifest(snapshot))
    from cazzubot.channels.plan import build_plan

    plan = build_plan(manifest, snapshot, delete=False)
    result = await apply_plan(guild, plan, delete=False)
    return result.errors
