"""Live executor: apply a :class:`Plan` against a real guild.

Bridges the pure parser/plan engine to the Discord API: snapshots a guild
into the same dict shape the engine consumes, applies a plan (create →
update → delete → reorder), and supports snapshot-based backups and
restores. Everything runs over hikari's REST client (no gateway, no local
cache — which lags mutations and produced phantom drift in the apply
loop); channel creates/edits/reorders go through hikari's own rate-limited
request path with the raw API payload keys.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import hikari
import pendulum
from hikari.internal import routes

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

REORDER_ATTEMPTS = 5

# manifest kind -> Discord channel type id (the raw API value)
CHANNEL_TYPE_ID = {
    "text": 0,
    "announcement": 5,
    "voice": 2,
    "forum": 15,
    "stage": 13,
    "category": 4,
}

# Kind lookup by the channel type's *name* so both discord.py and hikari
# channel objects resolve (hikari's enum names are GUILD_* prefixed).
_KIND_BY_TYPE_NAME = {
    "text": "text",
    "news": "announcement",
    "voice": "voice",
    "forum": "forum",
    "stage_voice": "stage",
    "category": "category",
    "GUILD_TEXT": "text",
    "GUILD_NEWS": "announcement",
    "GUILD_VOICE": "voice",
    "GUILD_FORUM": "forum",
    "GUILD_STAGE_VOICE": "stage",
    "GUILD_CATEGORY": "category",
}


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Outcome of an apply: errors plus the renames that actually ran."""

    errors: list[str]
    applied_renames: list[RenameOp]


# -- snapshots ---------------------------------------------------------------


async def snapshot_guild(
    client: hikari.api.RESTClient, guild_id: int
) -> list[ChannelSnapshot]:
    """The guild's channels as plain dicts, from a fresh API fetch.

    Channels come from the REST API, not the local cache — the cache lags
    the gateway after mutations, which produced phantom drift in the
    apply convergence loop.
    """
    return snapshot_channels(await client.fetch_guild_channels(guild_id))


def snapshot_channels(channels: Sequence[Any]) -> list[ChannelSnapshot]:
    """The channels as plain dicts (works on discord.py or hikari objects).

    Discord allows duplicate channel names; the engine keys channels by
    name, so every channel after the first with a given name is marked
    ``unsupported`` — it is kept as-is and never managed.
    """
    cats = {
        ch.id: ch.name for ch in channels if _kind_of(ch)[0] == "category"
    }
    # duplicate (non-first) categories are unmanaged; channels inside
    # them are unaddressable by name too — mark them unsupported so they
    # can never be matched, reordered or deleted
    seen_cats: set[str] = set()
    dup_cat_ids: set[int] = set()
    for ch in channels:
        if _kind_of(ch)[0] == "category":
            if ch.name in seen_cats:
                dup_cat_ids.add(ch.id)
            seen_cats.add(ch.name)
    out: list[ChannelSnapshot] = []
    seen: set[str] = set()
    for ch in channels:
        kind, unsupported = _kind_of(ch)
        category = (
            cats.get(ch.parent_id) if ch.parent_id is not None else None
        )
        snap = _snapshot_channel(ch, kind, category)
        if (
            unsupported
            or ch.name in seen
            or not _representable_name(ch.name)
            or (ch.parent_id is not None and ch.parent_id in dup_cat_ids)
        ):
            snap["unsupported"] = True
        seen.add(ch.name)
        out.append(snap)
    return out


def _kind_of(ch: Any) -> tuple[str, bool]:
    """(kind, unsupported) for a live channel object (discord.py or hikari)."""
    # hikari channels and anything unknown: resolve by the type name
    type_name = getattr(getattr(ch, "type", None), "name", None)
    kind = (
        _KIND_BY_TYPE_NAME.get(type_name)
        if type_name is not None
        else None
    )
    if kind is not None:
        return kind, False
    return type_name or "unknown", True


def _snapshot_channel(
    ch: Any, kind: str, category: str | None
) -> ChannelSnapshot:
    snap: ChannelSnapshot = {
        "id": str(ch.id),
        "name": ch.name,
        "kind": kind,
        "category": category,
        "position": getattr(ch, "position", 0),
        "nsfw": bool(
            getattr(ch, "nsfw", False) or getattr(ch, "is_nsfw", False)
        ),
        "slowmode": 0,
    }
    if kind in SLOWMODE_KINDS:
        snap["slowmode"] = int(
            getattr(ch, "slowmode_delay", 0)
            or getattr(ch, "rate_limit_per_user", 0)
            or getattr(ch, "default_thread_rate_limit_per_user", 0)
            or 0
        )
    if kind in VOICE_KINDS:
        snap["bitrate"] = int(getattr(ch, "bitrate", 0) or 0) // 1000
        snap["limit"] = int(getattr(ch, "user_limit", 0) or 0)
        snap["region"] = getattr(ch, "rtc_region", None)
        vqm = getattr(ch, "video_quality_mode", None)
        # server values: 1=auto, 2=1080
        raw = str(vqm.value) if vqm is not None else None
        snap["quality"] = {"1": "auto", "2": "1080"}.get(raw or "", raw)
    return snap


def _representable_name(name: str) -> bool:
    """True when a channel name round-trips through the manifest format.

    Mirrors the parser's line grammar: names containing ``->`` (rename
    syntax) or `` : `` (token separator), names ending with `` :`` (the
    parser's trailing-separator branch), names with leading/trailing
    whitespace, names starting with ``[`` (header syntax) or ``#``
    (comment syntax), and whitespace-only names can't be written
    unambiguously — the engine marks them unsupported instead.
    """
    if not name or name != name.strip():
        return False
    if "->" in name or " : " in name or name.endswith(" :"):
        return False
    if name[0] in "[#" or name.isspace():
        return False
    return True


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
    stamp = pendulum.now("UTC").format("YYYYMMDD-HHmmss")
    return base / f"channels-{stamp}.json"


# -- applying ----------------------------------------------------------------


async def apply_plan(
    client: hikari.api.RESTClient,
    guild_id: int,
    plan: Plan,
    *,
    delete: bool,
) -> ApplyResult:
    """Execute a plan, returning errors plus the renames that ran.

    One authoritative fresh channel view is threaded through the whole
    apply: lookups for the next operation use the verified state after
    the previous one. The local cache is never read — it lags the gateway.
    """
    errors: list[str] = []
    applied_renames: list[RenameOp] = []
    reason = "channels manifest apply"

    async def refresh() -> Sequence[Any]:
        return await client.fetch_guild_channels(guild_id)

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
            await client.edit_channel(
                channel.id, name=op.new, reason=reason
            )
        except hikari.HikariError as err:
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
                await _create_channel(
                    client, guild_id, op.spec, None, reason=reason
                )
            except hikari.HikariError as err:
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
            await _create_channel(
                client, guild_id, op.spec, parent, reason=reason
            )
        except hikari.HikariError as err:
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
            await _edit_channel(client, channel, op.changes, reason)
        except hikari.HikariError as err:
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
            if _kind_of(channel)[0] == "category":
                # re-verify the category is still childless right before
                # deleting — a channel created in it since the plan was
                # built would otherwise be cascade-deleted
                if any(
                    c.parent_id == op.id for c in current if c.id != op.id
                ):
                    errors.append(
                        f"delete {op.name}: category gained children since "
                        "the plan — skipping"
                    )
                    continue
            try:
                await client.delete_channel(channel.id, reason=reason)
            except hikari.HikariError as err:
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
            await reorder_guild(
                client, guild_id, plan.target, plan.in_scope_ids
            )
        except (hikari.HikariError, RuntimeError) as err:
            errors.append(f"reorder: {err}")

    return ApplyResult(errors=errors, applied_renames=applied_renames)


async def _create_channel(
    client: hikari.api.RESTClient,
    guild_id: int,
    spec: ChannelSpec,
    parent_id: int | None,
    *,
    reason: str,
) -> None:
    """Create a channel via the raw channel-create endpoint.

    Goes through hikari's own rate-limited request path with the raw API
    payload keys (categories included — hikari has no per-type category
    creator). The REST endpoint takes the payload directly, so the parent
    category never has to come from the local cache (which lags the
    gateway after a category was just created in the same apply).
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
    route = routes.POST_GUILD_CHANNELS.compile(guild=guild_id)
    await cast(Any, client)._request(  # noqa: SLF001  # raw payload path
        route,
        json={"type": CHANNEL_TYPE_ID[spec.kind], **payload},
        reason=reason,
    )


def _vqm(label: str) -> int:
    return QUALITY_VALUES[label]


async def _edit_channel(
    client: hikari.api.RESTClient,
    channel: Any,
    changes: dict[str, tuple[Any, Any]],
    reason: str,
) -> None:
    """Apply field changes via the raw PATCH /channels/{id} endpoint.

    hikari's ``edit_channel`` lacks the ``type`` field (text ↔
    announcement), so the raw path carries every field uniformly — same
    payload keys the old discord.py ``channel.edit`` sent.
    """
    payload: dict[str, Any] = {}
    for field_name, (_, new) in changes.items():
        if field_name == "kind":
            payload["type"] = 5 if new == "announcement" else 0
        elif field_name == "nsfw":
            payload["nsfw"] = new
        elif field_name == "slowmode":
            if _kind_of(channel)[0] == "forum":
                payload["default_thread_rate_limit_per_user"] = new
            else:
                payload["rate_limit_per_user"] = new
        elif field_name == "bitrate":
            payload["bitrate"] = new * 1000
        elif field_name == "limit":
            payload["user_limit"] = new
        elif field_name == "region":
            payload["rtc_region"] = None if new == "auto" else new
        elif field_name == "quality":
            payload["video_quality_mode"] = _vqm(new)
    route = routes.PATCH_CHANNEL.compile(channel=channel.id)
    await cast(Any, client)._request(  # noqa: SLF001  # raw payload path
        route, json=payload, reason=reason
    )


def _attr_mismatches(
    channel: Any, changes: dict[str, tuple[Any, Any]]
) -> list[str]:
    """Field names in ``changes`` that the live channel doesn't match yet."""
    out: list[str] = []
    for field_name, (_, want) in changes.items():
        if field_name == "kind":
            have = (
                "announcement"
                if _kind_of(channel)[0] == "announcement"
                else "text"
            )
            if have != want:
                out.append("kind")
        elif field_name == "nsfw":
            if bool(getattr(channel, "is_nsfw", False)) != want:
                out.append("nsfw")
        elif field_name == "slowmode":
            if _kind_of(channel)[0] == "forum":
                have = int(
                    getattr(
                        channel, "default_thread_rate_limit_per_user", 0
                    )
                    or 0
                )
            else:
                have = int(getattr(channel, "rate_limit_per_user", 0) or 0)
            if have != want:
                out.append("slowmode")
        elif field_name == "bitrate":
            if int(getattr(channel, "bitrate", 0) or 0) != want * 1000:
                out.append("bitrate")
        elif field_name == "limit":
            if int(getattr(channel, "user_limit", 0) or 0) != want:
                out.append("limit")
        elif field_name == "region":
            # hikari can't read rtc_region (Discord deprecated regions);
            # the edit still goes through the raw endpoint, but the live
            # value is unreadable here, so skip verification.
            pass
        elif field_name == "quality":
            vqm = getattr(channel, "video_quality_mode", None)
            raw: int | None = vqm.value if vqm is not None else None
            have_quality: str | None = None
            if raw is not None:
                have_quality = {1: "auto", 2: "1080"}.get(raw)
            if have_quality != want:
                out.append("quality")
    return out


# -- reorder ----------------------------------------------------------------


def _category_ids(
    channels: Sequence[Any], managed_ids: set[int]
) -> dict[str, int]:
    """Category name → id, preferring managed (in-scope) categories.

    Discord allows duplicate category names; first occurrence wins, with
    managed ids taking precedence so a colliding out-of-scope category
    can never be the move target.
    """
    cat_ids: dict[str, int] = {}
    for c in channels:
        if _kind_of(c)[0] == "category" and c.id in managed_ids:
            if c.name is not None:
                cat_ids.setdefault(c.name, c.id)
    for c in channels:
        if _kind_of(c)[0] == "category" and c.name is not None:
            cat_ids.setdefault(c.name, c.id)
    return cat_ids


async def reorder_guild(
    client: hikari.api.RESTClient,
    guild_id: int,
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
      moved with its own ``edit_channel(parent_category=...)`` call;
    - **positions** — the remaining reorder is one bulk PATCH per
      attempt.

    Channels are re-fetched from the API and the passes re-applied until
    the layout holds — Discord resolves moves inconsistently in a single
    payload and the gateway lags the local cache. Bounded attempts, then
    an error if it never converges.
    """
    for _ in range(REORDER_ATTEMPTS):
        parent_moves = await _parent_moves(
            client, guild_id, target, managed_ids
        )
        for channel_id, parent_id in parent_moves:
            await client.edit_channel(
                channel_id,
                parent_category=(
                    parent_id
                    if parent_id is not None
                    else hikari.UNDEFINED
                ),
                reason="channels manifest apply",
            )
        payload = await _reorder_payload(
            client, guild_id, target, managed_ids
        )
        if not parent_moves and not payload:
            return
        if payload:
            route = routes.PATCH_GUILD_CHANNELS.compile(guild=guild_id)
            await cast(Any, client)._request(  # noqa: SLF001  # bulk positions
                route, json=payload, reason="channels manifest apply"
            )
        await asyncio.sleep(
            0.6
        )  # let the gateway settle before re-reading
    payload = await _reorder_payload(client, guild_id, target, managed_ids)
    if payload:
        raise RuntimeError(
            f"reorder did not converge after {REORDER_ATTEMPTS} attempts — "
            f"{len(payload)} move(s) remain; re-run channels apply"
        )


async def _parent_moves(
    client: hikari.api.RESTClient,
    guild_id: int,
    target: dict[tuple[str | None, str], list[str]],
    managed_ids: tuple[int, ...],
) -> list[tuple[int, int | None]]:
    """(channel id, target parent id) for every channel changing category.

    Names resolve only among ``managed_ids`` (the plan's in-scope set),
    so a colliding out-of-scope name can never hijack the move.
    """
    channels = await client.fetch_guild_channels(guild_id)
    cat_ids = _category_ids(channels, set(managed_ids))
    by_name: dict[str, Any] = {}
    for c in channels:
        if c.id in managed_ids and c.name is not None:
            by_name.setdefault(c.name, c)

    moves: list[tuple[int, int | None]] = []
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
            if ch.parent_id != parent_id:
                moves.append((ch.id, parent_id))
                seen.add(ch.id)
    return moves


async def _reorder_payload(
    client: hikari.api.RESTClient,
    guild_id: int,
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
    channels = await client.fetch_guild_channels(guild_id)
    cat_ids = _category_ids(channels, set(managed_ids))
    by_name: dict[str, Any] = {}
    for c in channels:
        if c.id in managed_ids and c.name is not None:
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
                (c.parent_id == parent_id)
                if category is not None
                else c.parent_id is None
            )
            and bucket_of(_kind_of(c)[0]) == section
        ]
        members.sort(key=lambda c: getattr(c, "position", 0))
        ordered_target = [by_name[n] for n in names if n in by_name]

        # anchor walk: channels not in the target keep their current slots
        # (out-of-scope channels, strays and duplicates never move);
        # target channels fill the remaining slots in manifest order,
        # extending the block when channels are arriving from elsewhere.
        # Kept channels pin their own index — with duplicate names, each
        # occurrence must pin its own slot (members.index would pin the
        # first occurrence twice).
        kept = {c.name for c in members} - set(names)
        final: list[Any | None] = [None] * len(members)
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
    client: hikari.api.RESTClient,
    guild_id: int,
    snapshot: list[ChannelSnapshot],
) -> list[str]:
    """Bring the guild back toward a snapshot (never deletes anything)."""
    from cazzubot.channels.export import render_manifest

    manifest = parse(render_manifest(snapshot))
    from cazzubot.channels.plan import build_plan

    plan = build_plan(manifest, snapshot, delete=False)
    result = await apply_plan(client, guild_id, plan, delete=False)
    return result.errors
