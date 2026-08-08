"""Roles domain of the admin CLI: export/diff/check/apply/restore.

Thin shell over the ``cazzubot.roles`` engine — the parser/plan/executor
stay in the engine; this module only wires verbs to them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import discord

from cazzubot.cli.core import (
    Command,
    DEFAULT_BACKUP_DIR,
    Domain,
    confirm,
    export_stamp,
    require_guild,
)
from cazzubot.config import Config
from cazzubot.roles import executor
from cazzubot.roles.export import render_manifest
from cazzubot.roles.parser import (
    ManifestError,
    Manifest,
    parse,
    rewrite_renames,
)
from cazzubot.roles.plan import Plan, RenameOp, build_plan


async def cmd_export(
    client: discord.Client, config: Config, args: argparse.Namespace
) -> int:
    """Write a fresh manifest from the live guild."""
    guild = require_guild(client, config)
    if guild is None:
        return 1
    roles = await executor.snapshot_guild(guild)
    text = render_manifest(
        roles,
        source=f"live guild {guild.name}",
        exported=export_stamp(),
    )
    args.file.write_text(text, encoding="utf-8")
    print(f"wrote {args.file} ({text.count(chr(10))} lines)")
    return 0


async def cmd_diff(
    client: discord.Client, config: Config, args: argparse.Namespace
) -> int:
    """Show the plan; exit 1 when the guild drifts."""
    plan = await _plan(client, config, args, delete=args.delete)
    if plan is None:
        return 1
    print(plan.render())
    return 0 if plan.is_clean() else 1


async def cmd_check(
    client: discord.Client, config: Config, args: argparse.Namespace
) -> int:
    """Hook-friendly drift check: exit 1 on drift, prints a summary."""
    plan = await _plan(client, config, args, delete=False)
    if plan is None:
        return 1
    if not plan.is_clean():
        print(f"DRIFT: {plan.summary()}")
        print(plan.render())
        return 1
    print("clean")
    return 0


async def cmd_apply(
    client: discord.Client, config: Config, args: argparse.Namespace
) -> int:
    """Reconcile the guild to the file, with backup + confirmation."""
    manifest_text = _read_manifest(args.file)
    if manifest_text is None:
        return 1
    try:
        manifest = parse(manifest_text)
    except ManifestError as err:
        for issue in err.issues:
            print(f"{args.file}:{issue}", file=sys.stderr)
        return 1
    plan = await _plan_from(client, config, manifest, delete=args.delete)
    if plan is None:
        return 1
    if plan.is_clean():
        print("clean — nothing to do")
        return 0
    print(plan.render())
    if plan.reorder_blocked:
        # refuse before mutating anything — a half-applied reorder leaves
        # created roles stranded at the bottom (the "created but didn't
        # move" trap)
        blockers = plan.moving_unmovable()
        print(
            f"error: reorder blocked — the target order would move role(s) that can't be moved: {', '.join(blockers)}",
            file=sys.stderr,
        )
        print(
            "  roles at or above the bot's highest role need the bot role raised first. Place the new order below them instead.",
            file=sys.stderr,
        )
        return 1
    if plan.rename_conflicts:
        print(
            "error: rename conflicts — resolve them in the manifest first",
            file=sys.stderr,
        )
        return 1
    if not confirm(args):
        print("aborted")
        return 1
    guild = require_guild(client, config)
    assert guild is not None
    backup = executor.backup_path(DEFAULT_BACKUP_DIR)
    executor.save_snapshot(backup, await executor.snapshot_guild(guild))
    print(f"backup: {backup}")

    # apply, then verify the end state against the manifest and converge:
    # re-plan from a fresh snapshot and re-apply any residual drift
    # (bounded), so operations that silently didn't take effect are caught.
    all_errors: list[str] = []
    all_applied: list[RenameOp] = []
    current_plan = plan
    for _ in range(3):
        result = await executor.apply_plan(
            guild, current_plan, delete=args.delete
        )
        all_errors.extend(result.errors)
        all_applied.extend(result.applied_renames)
        if result.errors:
            break  # a real failure — don't paper over it with retries
        current_plan = await _plan_from(
            client, config, manifest, delete=args.delete
        )
        assert current_plan is not None
        if not current_plan.needs_apply:
            break  # only manifest cleanup remains — the rewrite fixes it
    else:
        print(
            "warning: apply did not fully converge — remaining drift:",
            file=sys.stderr,
        )
        print(current_plan.render(), file=sys.stderr)
        all_errors.append("apply did not fully converge")

    for err in all_errors:
        print(f"✖ {err}", file=sys.stderr)
    applied = list(all_applied)
    applied.extend(plan.cleanup_renames)
    if applied:
        renames = [(op.line, op.old, op.new) for op in applied]
        args.file.write_text(
            rewrite_renames(manifest_text, renames),
            encoding="utf-8",
        )
        print(
            f"manifest updated: {len(renames)} rename(s) applied ({args.file})"
        )
    if all_errors:
        return 1
    print("done")
    return 0


async def cmd_restore(
    client: discord.Client, config: Config, args: argparse.Namespace
) -> int:
    """Bring the guild back toward a backup snapshot (never deletes)."""
    try:
        snapshot = executor.load_snapshot(args.snapshot)
    except (OSError, ValueError) as err:
        print(f"error: cannot read snapshot: {err}", file=sys.stderr)
        return 1
    guild = require_guild(client, config)
    if guild is None:
        return 1
    roles = await executor.snapshot_guild(guild)
    manifest = parse(render_manifest(snapshot))
    plan = build_plan(
        manifest,
        roles,
        bot_top_role_id=guild.me.top_role.id,
        delete=False,
    )
    print(plan.render())
    if plan.is_clean():
        print("already matches the snapshot")
        return 0
    if not confirm(args):
        print("aborted")
        return 1
    backup = executor.backup_path(DEFAULT_BACKUP_DIR)
    executor.save_snapshot(backup, roles)
    print(f"backup: {backup}")
    result = await executor.apply_plan(guild, plan, delete=False)
    for err in result.errors:
        print(f"✖ {err}", file=sys.stderr)
    if result.errors:
        return 1
    print("done")
    return 0


# -- helpers (lower-level; used by the handlers above) -----------------------


def _add_file_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("roles.manifest"),
        help="manifest path (default: roles.manifest)",
    )


def _add_diff_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--delete",
        action="store_true",
        help="include delete candidates in the preview",
    )


def _add_apply_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="also delete roles not listed in the manifest",
    )


def _add_restore_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )


async def _plan(
    client: discord.Client,
    config: Config,
    args: argparse.Namespace,
    *,
    delete: bool,
) -> Plan | None:
    manifest = load_manifest(args.file)
    if manifest is None:
        return None
    return await _plan_from(client, config, manifest, delete=delete)


async def _plan_from(
    client: discord.Client,
    config: Config,
    manifest: Manifest,
    *,
    delete: bool,
) -> Plan | None:
    guild = require_guild(client, config)
    if guild is None:
        return None
    roles = await executor.snapshot_guild(guild)
    return build_plan(
        manifest,
        roles,
        bot_top_role_id=guild.me.top_role.id,
        delete=delete,
        member_counts=executor.member_counts(guild),
    )


def load_manifest(path: Path) -> Manifest | None:
    """Read + parse the manifest; print issues and return None on failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        print(f"error: cannot read {path}: {err}", file=sys.stderr)
        return None
    try:
        return parse(text)
    except ManifestError as err:
        for issue in err.issues:
            print(f"{path}:{issue}", file=sys.stderr)
        return None


def _read_manifest(path: Path) -> str | None:
    """Read the manifest file; print the error and return None on failure."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as err:
        print(f"error: cannot read {path}: {err}", file=sys.stderr)
        return None


domain = Domain(
    name="roles",
    help="manage the role manifest (export/diff/check/apply/restore)",
    common_args=(_add_file_args,),
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
            add_args=_add_diff_args,
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
            add_args=_add_apply_args,
        ),
        "restore": Command(
            cmd_restore,
            live=True,
            help="bring the guild back toward a backup snapshot",
            add_args=_add_restore_args,
        ),
    },
)
