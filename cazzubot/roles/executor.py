"""Live executor: apply a :class:`Plan` against a real guild.

Bridges the pure parser/plan engine to the Discord API: snapshots a guild
into the same dict shape the engine consumes, applies a plan (create →
update → delete → reorder), and supports snapshot-based backups and
restores. Everything runs over the REST client — no gateway, no cache
(which lags mutations and produced phantom drift in the apply loop).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import hikari
import pendulum

from cazzubot.roles.parser import (
    CANONICAL_FLAGS,
    RoleSpec,
    flag_bit,
    parse,
)
from cazzubot.roles.plan import Plan, RenameOp
from cazzubot.roles.snapshot import RoleSnapshot

EVERYONE = "@everyone"

REORDER_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Outcome of an apply: errors plus the renames that actually ran."""

    errors: list[str]
    applied_renames: list[RenameOp]


# -- snapshots ---------------------------------------------------------------


async def snapshot_guild(
    client: hikari.api.RESTClient, guild_id: int
) -> list[RoleSnapshot]:
    """The guild's roles as plain dicts, top-down (index 0 = highest).

    Roles come from a fresh API fetch, not the local cache — the cache
    lags the gateway after mutations, which produced phantom drift in the
    apply convergence loop.
    """
    roles = sorted(
        await client.fetch_roles(guild_id),
        key=lambda r: r.position,
        reverse=True,
    )
    return [snapshot_role(role, i) for i, role in enumerate(roles)]


def snapshot_role(role: hikari.Role, pos: int) -> RoleSnapshot:
    icon: str | None = None
    if role.unicode_emoji:
        icon = role.unicode_emoji
    elif role.icon_hash is not None:
        icon = str(role.make_icon_url())
    perms = [
        name
        for name in sorted(CANONICAL_FLAGS)
        if bool(
            role.permissions & hikari.Permissions(CANONICAL_FLAGS[name])
        )
    ]
    # hikari has no RoleTags; managed roles are never user-manageable,
    # which is the only property the plan reads the tags for.
    tags = ["bot"] if role.is_managed else []
    color = int(role.color) if role.color is not None else 0
    return {
        "position": pos,
        "id": str(role.id),
        "name": role.name,
        "color": f"#{color:06x}" if color else None,
        "hoisted": role.is_hoisted,
        "mentionable": role.is_mentionable,
        "managed": role.is_managed,
        "permissions": perms,
        "icon": icon,
        "tags": tags,
    }


async def member_counts(
    client: hikari.api.RESTClient, guild_id: int
) -> dict[int, int]:
    """role id → member count (needs the members intent; {} if unavailable)."""
    counts: dict[int, int] = {}
    members = client.fetch_members(guild_id)
    async for member in members:
        for rid in member.role_ids:
            counts[int(rid)] = counts.get(int(rid), 0) + 1
    return counts


async def bot_top_role_id(
    client: hikari.api.RESTClient, guild_id: int
) -> int | None:
    """The bot's highest role id (``None`` if the bot has no roles)."""
    me = await client.fetch_my_user()
    member = await client.fetch_member(guild_id, me.id)
    roles = await client.fetch_roles(guild_id)
    candidates = [r for r in roles if r.id in member.role_ids]
    if not candidates:
        return None
    return int(max(candidates, key=lambda r: r.position).id)


def save_snapshot(path: Path, roles: list[RoleSnapshot]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(roles, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_snapshot(path: Path) -> list[RoleSnapshot]:
    return json.loads(path.read_text(encoding="utf-8"))


def backup_path(base: Path) -> Path:
    """``<base>/roles-YYYYMMDD-HHMMSS.json`` in UTC."""
    stamp = pendulum.now("UTC").format("YYYYMMDD-HHmmss")
    return base / f"roles-{stamp}.json"


# -- applying ----------------------------------------------------------------


def _color(hex_color: str | None) -> hikari.Color:
    if not hex_color:
        return hikari.Color(0)
    return hikari.Color(int(hex_color.lstrip("#"), 16))


def _permissions(names: list[str] | frozenset[str]) -> hikari.Permissions:
    perms = hikari.Permissions.NONE
    for name in names:
        perms |= hikari.Permissions(flag_bit(name))
    return perms


def _attr_mismatches(
    role: hikari.Role, new: Mapping[str, Any]
) -> list[str]:
    """Attribute names in ``new`` that the live role doesn't match yet."""
    out: list[str] = []
    if "color" in new and int(role.color or 0) != int(new["color"]):
        out.append("color")
    if "hoist" in new and role.is_hoisted != new["hoist"]:
        out.append("hoist")
    if "mentionable" in new and role.is_mentionable != new["mentionable"]:
        out.append("mentionable")
    if "permissions" in new and role.permissions != cast(
        hikari.Permissions, new["permissions"]
    ):
        out.append("permissions")
    return out


def _create_kwargs(
    spec: RoleSpec, perms: frozenset[str]
) -> dict[str, Any]:
    """Build create_role kwargs (icon needs display_icon, like edit)."""
    kwargs: dict[str, Any] = {
        "name": spec.name,
        "color": _color(spec.color),
        "hoist": spec.hoist,
        "mentionable": spec.mentionable,
        "permissions": _permissions(perms),
    }
    if spec.icon:
        kwargs["icon"] = spec.icon
    return kwargs


async def apply_plan(
    client: hikari.api.RESTClient,
    guild_id: int,
    plan: Plan,
    *,
    delete: bool,
) -> ApplyResult:
    """Execute a plan, returning errors plus the renames that ran.

    One authoritative fresh role view is threaded through the whole apply:
    lookups for the next operation use the verified state after the
    previous one. The local cache is never read — it lags the gateway.
    """
    errors: list[str] = []
    applied_renames: list[RenameOp] = []
    reason = "roles manifest apply"

    async def refresh() -> dict[int, hikari.Role]:
        """Fresh API view of roles by id — the working set AND the
        verification data."""
        return {
            role.id: role for role in await client.fetch_roles(guild_id)
        }

    current = await refresh()

    # 0. renames first — later steps match roles under their new names
    for op in plan.renames:
        role = next(
            (r for r in current.values() if r.name == op.old), None
        )
        if role is None:
            errors.append(f"rename {op.old}: role not found")
            continue
        try:
            await client.edit_role(
                guild_id, role.id, name=op.new, reason=reason
            )
        except hikari.HikariError as err:
            errors.append(f"rename {op.old}: {err}")
            continue
        current = await refresh()
        names = {r.name for r in current.values()}
        if op.new not in names or op.old in names:
            errors.append(
                f"rename {op.old}: did not take effect (verification)"
            )
        else:
            applied_renames.append(op)

    # 1. creates
    for op in plan.creates:
        try:
            kwargs = _create_kwargs(op.spec, op.permissions)
            await client.create_role(guild_id, **kwargs, reason=reason)
        except hikari.HikariError as err:
            errors.append(f"create {op.spec.name}: {err}")
            continue
        current = await refresh()
        if op.spec.name not in {r.name for r in current.values()}:
            errors.append(
                f"create {op.spec.name}: not present after verification"
            )

    # 2. updates
    for op in plan.updates:
        role = current.get(op.id)
        if role is None:
            errors.append(f"update {op.name}: role not found")
            continue
        kwargs: dict[str, Any] = {}
        if "color" in op.changes:
            kwargs["color"] = _color(op.changes["color"][1])
        if "hoist" in op.changes:
            kwargs["hoist"] = op.changes["hoist"][1]
        if "mentionable" in op.changes:
            kwargs["mentionable"] = op.changes["mentionable"][1]
        if "permissions" in op.changes:
            kwargs["permissions"] = _permissions(
                op.changes["permissions"][1]
            )
        if "icon" in op.changes:
            icon = op.changes["icon"][1]
            if icon:
                kwargs["icon"] = icon
        try:
            await client.edit_role(
                guild_id, op.id, **kwargs, reason=reason
            )
        except hikari.HikariError as err:
            errors.append(f"update {op.name}: {err}")
            continue
        current = await refresh()
        verified = current.get(op.id)
        if verified is None:
            errors.append(f"update {op.name}: role vanished after edit")
        else:
            mismatches = _attr_mismatches(verified, kwargs)
            if mismatches:
                errors.append(
                    f"update {op.name}: {', '.join(mismatches)} did not take effect (verification)"
                )

    # 3. deletes
    if delete:
        for op in plan.deletes:
            role = current.get(op.id)
            if role is None:
                continue
            try:
                await client.delete_role(guild_id, op.id, reason=reason)
            except hikari.HikariError as err:
                errors.append(f"delete {op.name}: {err}")
                continue
            current = await refresh()
            if op.id in current:
                errors.append(
                    f"delete {op.name}: still present after verification"
                )

    # 4. reorder (blocked → reported, never partially applied)
    if plan.needs_reorder:
        if plan.reorder_blocked:
            errors.append(
                "reorder skipped: roles sit above the bot's highest role"
            )
        else:
            try:
                await reorder_guild(client, guild_id, plan.target_order)
            except hikari.HikariError as err:
                errors.append(f"reorder: {err}")

    return ApplyResult(errors=errors, applied_renames=applied_renames)


async def reorder_guild(
    client: hikari.api.RESTClient,
    guild_id: int,
    target_order: list[str],
) -> None:
    """Bulk-move roles so the sidebar matches ``target_order`` (top-down).

    Unmovable roles (``@everyone``, anything at or above the bot's own
    highest role) keep their current positions and act as anchors: walking
    the target top-down, each movable role is assigned the position just
    below the previous role. This produces a strictly-decreasing position
    sequence that works even on a non-clean layout — e.g. after creates,
    which Discord places at position 1 without shifting existing roles,
    leaving duplicates. It never sends a position at/above the bot's top
    role and never collides with unsent roles.

    Roles are re-fetched from the API and the payload is re-applied until
    the target order holds: creates leave duplicate positions (a pile at
    position 1) that Discord resolves inconsistently in a single payload,
    and the gateway lags the local cache. Bounded attempts, then an error
    if it never converges.
    """
    for _ in range(REORDER_ATTEMPTS):
        moves = await _reorder_moves(client, guild_id, target_order)
        if not moves:
            return
        # hikari's reposition_roles takes {position: role_id}
        await client.reposition_roles(
            guild_id,
            {position: role_id for role_id, position in moves.items()},
            reason="roles manifest apply",
        )
        await asyncio.sleep(
            0.6
        )  # let the gateway settle before re-reading
    moves = await _reorder_moves(client, guild_id, target_order)
    if moves:
        raise RuntimeError(
            f"reorder did not converge after {REORDER_ATTEMPTS} attempts — {len(moves)} move(s) remain; re-run roles apply"
        )


async def _reorder_moves(
    client: hikari.api.RESTClient,
    guild_id: int,
    target_order: list[str],
) -> dict[int, int]:
    """Compute the position payload that moves the guild toward ``target_order``."""
    fresh = await client.fetch_roles(guild_id)
    by_name = {role.name: role for role in fresh}
    everyone = next(
        (r for r in fresh if r.id == guild_id), None
    )  # @everyone's id == guild id
    if everyone is None:
        raise RuntimeError("guild has no @everyone role?!")
    me = await client.fetch_my_user()
    member = await client.fetch_member(guild_id, me.id)
    bot_role_ids = set(member.role_ids)
    top_position = max(
        (role.position for role in fresh if role.id in bot_role_ids),
        default=0,
    )
    ordered = [by_name[name] for name in target_order if name in by_name]
    ordered.append(everyone)  # @everyone stays at the bottom
    if len(ordered) != len(fresh):
        raise RuntimeError(
            "target order doesn't cover every role — refusing to reorder"
        )

    def unmovable(role: hikari.Role) -> bool:
        # Discord positions: 0 = @everyone at the BOTTOM, higher = higher in
        # the sidebar. Only @everyone and roles at or above the bot's own
        # highest role can't be moved. Managed roles (bot, boost, shop,
        # linked) ARE movable via the API — verified empirically.
        return role.id == everyone.id or role.position >= top_position

    moves: dict[int, int] = {}  # role_id -> position
    next_position: int | None = None
    for role in ordered:
        if unmovable(role):
            # anchor: everything below it must fit below its position
            next_position = role.position - 1
            continue
        if next_position is None:
            raise RuntimeError(
                "no unmovable anchor above the first movable role — the target order places a role above the bot"
            )
        position = next_position
        if role.position != position:
            moves[int(role.id)] = position
        next_position -= 1
    if not moves:
        return {}

    # safety net: never send a position at/above the bot's top role, and
    # never send colliding positions (Discord would 403 or corrupt)
    assigned: set[int] = set()
    for role_id, position in moves.items():
        if position >= top_position:
            raise RuntimeError(
                f"reorder would place a role at position {position}, at or above the bot's highest role — move it below that in the manifest"
            )
        if position in assigned:
            raise RuntimeError(
                f"reorder assigns position {position} twice — the guild's role positions are inconsistent; fix positions manually or re-export"
            )
        assigned.add(position)
    return moves


async def restore_guild(
    client: hikari.api.RESTClient,
    guild_id: int,
    snapshot: list[RoleSnapshot],
) -> list[str]:
    """Bring the guild back toward a snapshot (never deletes anything)."""
    from cazzubot.roles.export import render_manifest

    manifest = parse(render_manifest(snapshot))
    from cazzubot.roles.plan import build_plan

    plan = build_plan(
        manifest,
        snapshot,
        bot_top_role_id=await bot_top_role_id(client, guild_id),
        delete=False,
    )
    result = await apply_plan(client, guild_id, plan, delete=False)
    return result.errors
