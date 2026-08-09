"""Roles domain of the admin CLI: export/diff/check/apply/restore.

Thin shell: the parser/plan/executor stay in the ``cazzubot.roles``
engine and the verbs live in ``cazzubot.manifest.cli`` — this module
only wires the two together.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import hikari

from cazzubot.cli.core import (
    Command,
    DEFAULT_BACKUP_DIR,
    Domain,
    EXPORT_PRESETS,
    require_guild,
)
from cazzubot.config import Config
from cazzubot.manifest.cli import (
    ManifestDomain,
    add_apply_args,
    add_diff_args,
    add_file_args,
    add_restore_args,
    run_apply,
    run_check,
    run_diff,
    run_export,
    run_restore,
)
from cazzubot.roles import executor
from cazzubot.roles.export import render_manifest
from cazzubot.roles.parser import Manifest, parse
from cazzubot.roles.plan import Plan, build_plan


async def cmd_export(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
) -> int:
    """Write a fresh manifest from the live guild."""
    return await run_export(client, config, args, _DOMAIN)


async def cmd_diff(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
) -> int:
    """Show the plan; exit 1 when the guild drifts."""
    return await run_diff(client, config, args, _DOMAIN)


async def cmd_check(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
) -> int:
    """Hook-friendly drift check: exit 1 on drift, prints a summary."""
    return await run_check(client, config, args, _DOMAIN)


async def cmd_apply(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
) -> int:
    """Reconcile the guild to the file, with backup + confirmation."""
    return await run_apply(client, config, args, _DOMAIN)


async def cmd_restore(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
) -> int:
    """Bring the guild back toward a backup snapshot (never deletes)."""
    return await run_restore(client, config, args, _DOMAIN)


# -- helpers (lower-level; used by the wiring above) -------------------------


async def _plan_from(
    client: hikari.api.RESTClient,
    config: Config,
    manifest: Manifest,
    _args: argparse.Namespace,
    *,
    delete: bool,
) -> Plan | None:
    guild = await require_guild(client, config)
    if guild is None:
        return None
    roles = await executor.snapshot_guild(client, config.guild_id)
    member_counts = (
        await executor.member_counts(client, config.guild_id)
        if delete
        else None
    )
    return build_plan(
        manifest,
        roles,
        bot_top_role_id=await executor.bot_top_role_id(
            client, config.guild_id
        ),
        delete=delete,
        member_counts=member_counts,
    )


def _reorder_guard(plan: Plan) -> str | None:
    """Block apply when the target order would move unmovable roles."""
    if not plan.reorder_blocked:
        return None
    blockers = plan.moving_unmovable()
    return (
        "reorder blocked — the target order would move role(s) that can't "
        f"be moved: {', '.join(blockers)}"
        "\n  roles at or above the bot's highest role need the bot role "
        "raised first. Place the new order below them instead."
    )


_DOMAIN = ManifestDomain(
    name="roles",
    backup_dir=DEFAULT_BACKUP_DIR,
    snapshot=executor.snapshot_guild,
    render=lambda snap, source, exported: render_manifest(
        snap, presets=EXPORT_PRESETS, source=source, exported=exported
    ),
    parse=parse,
    plan_from=_plan_from,
    apply=executor.apply_plan,
    guard=_reorder_guard,
)

domain = Domain(
    name="roles",
    help="manage the role manifest (export/diff/check/apply/restore)",
    common_args=(add_file_args(Path("roles.manifest")),),
    commands={
        "export": Command(
            cmd_export,
            live=True,
            help="write a fresh manifest from the guild",
        ),
        "diff": Command(
            cmd_diff,
            live=True,
            help="show the plan, change nothing",
            add_args=add_diff_args,
        ),
        "check": Command(
            cmd_check,
            live=True,
            help="print drift summary; exit 1 if the guild drifts",
        ),
        "apply": Command(
            cmd_apply,
            live=True,
            help="reconcile the guild to the file",
            add_args=add_apply_args,
        ),
        "restore": Command(
            cmd_restore,
            live=True,
            help="bring the guild back toward a backup snapshot",
            add_args=add_restore_args,
        ),
    },
)
