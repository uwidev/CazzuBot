"""Channels domain of the admin CLI: export/diff/check/apply/restore.

Thin shell: the parser/plan/executor stay in the ``cazzubot.channels``
engine and the verbs live in ``cazzubot.manifest.cli`` — this module
only wires the two together.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import hikari

from cazzubot.channels import executor
from cazzubot.channels.export import render_manifest
from cazzubot.channels.parser import Manifest, parse
from cazzubot.channels.plan import Plan, build_plan
from cazzubot.cli.core import (
    Command,
    Domain,
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

CHANNELS_BACKUP_DIR = Path("data/channels_backups")


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


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope-below",
        metavar="CATEGORY",
        default=None,
        help="only manage the [CATEGORY] group and everything after it "
        "(groups above are kept as-is)",
    )


async def _plan_from(
    client: hikari.api.RESTClient,
    config: Config,
    manifest: Manifest,
    args: argparse.Namespace,
    *,
    delete: bool | None = None,
) -> Plan | None:
    guild = await require_guild(client, config)
    if guild is None:
        return None
    channels = await executor.snapshot_guild(client, config.guild_id)
    if delete is None:
        delete = bool(getattr(args, "delete", False))
    try:
        return build_plan(
            manifest,
            channels,
            scope_below=getattr(args, "scope_below", None),
            delete=delete,
        )
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return None


def _type_change_guard(plan: Plan) -> str | None:
    """Block apply when the plan contains unsupported type changes."""
    if not plan.type_changes:
        return None
    return "unsupported type changes — delete+recreate those channels manually"


_DOMAIN = ManifestDomain(
    name="channels",
    backup_dir=CHANNELS_BACKUP_DIR,
    snapshot=executor.snapshot_guild,
    render=lambda snap, source, exported: render_manifest(
        snap, source=source, exported=exported
    ),
    parse=parse,
    plan_from=_plan_from,
    apply=executor.apply_plan,
    guard=_type_change_guard,
)

domain = Domain(
    name="channels",
    help="manage the channel manifest (export/diff/check/apply/restore)",
    common_args=(
        add_file_args(Path("channels.manifest")),
        _add_scope_args,
    ),
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
