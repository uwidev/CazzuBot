"""Channels domain of the admin CLI: export/diff/check/apply/restore.

Thin shell over the ``cazzubot.channels`` engine — the parser/plan/
executor stay in the engine; this module only wires verbs to them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import hikari

from cazzubot.channels import executor
from cazzubot.channels.export import render_manifest
from cazzubot.channels.parser import (
    Manifest,
    ManifestError,
    parse,
    rewrite_renames,
)
from cazzubot.channels.plan import Plan, build_plan
from cazzubot.cli.core import (
    Command,
    Domain,
    confirm,
    export_stamp,
    require_guild,
)
from cazzubot.config import Config

CHANNELS_BACKUP_DIR = Path("data/channels_backups")


async def cmd_export(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
) -> int:
    """Write a fresh manifest from the live guild."""
    guild = await require_guild(client, config)
    if guild is None:
        return 1
    channels = await executor.snapshot_guild(client, config.guild_id)
    text = render_manifest(
        channels,
        source=f"live guild {guild.name}",
        exported=export_stamp(),
    )
    args.file.write_text(text, encoding="utf-8")
    print(f"wrote {args.file} ({text.count(chr(10))} lines)")
    return 0


async def cmd_diff(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
) -> int:
    """Show the plan; exit 1 when the guild drifts."""
    plan = await _plan(client, config, args, delete=args.delete)
    if plan is None:
        return 1
    print(plan.render())
    return 0 if plan.is_clean() else 1


async def cmd_check(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
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
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
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
    plan = await _plan_from(client, config, manifest, args)
    if plan is None:
        return 1
    if plan.is_clean():
        print("clean — nothing to do")
        return 0
    print(plan.render())
    if plan.type_changes:
        print(
            "error: unsupported type changes — delete+recreate those channels manually",
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
    guild = await require_guild(client, config)
    assert guild is not None
    backup = executor.backup_path(CHANNELS_BACKUP_DIR)
    executor.save_snapshot(
        backup, await executor.snapshot_guild(client, config.guild_id)
    )
    print(f"backup: {backup}")

    # apply, then verify the end state against the manifest and converge:
    # re-plan from a fresh snapshot and re-apply any residual drift
    # (bounded), so operations that silently didn't take effect are caught.
    # Rename lines are rewritten into the manifest *inside* the loop —
    # re-planning against the still-unrewritten file would otherwise see
    # the old and new names coexisting (e.g. a duplicate-named channel)
    # and report a permanent rename conflict.
    all_errors: list[str] = []
    current_plan = plan
    for _ in range(3):
        result = await executor.apply_plan(
            client, config.guild_id, current_plan, delete=args.delete
        )
        all_errors.extend(result.errors)
        applied = list(result.applied_renames)
        applied.extend(current_plan.cleanup_renames)
        if applied:
            renames = [(op.line, op.old, op.new) for op in applied]
            rewritten = rewrite_renames(manifest_text, renames)
            try:
                manifest = parse(rewritten)
            except ManifestError as err:
                all_errors.append(
                    f"manifest rewrite did not re-parse: {err}"
                )
                break
            try:
                _atomic_write(args.file, rewritten)
            except OSError as err:
                all_errors.append(f"manifest write failed: {err}")
                break
            manifest_text = rewritten
            print(
                f"manifest updated: {len(renames)} rename(s) applied "
                f"({args.file})"
            )
        if result.errors:
            break  # a real failure — don't paper over it with retries
        current_plan = await _plan_from(client, config, manifest, args)
        assert current_plan is not None
        if not current_plan.needs_apply:
            break  # the guild matches the manifest
    else:
        print(
            "warning: apply did not fully converge — remaining drift:",
            file=sys.stderr,
        )
        print(current_plan.render(), file=sys.stderr)
        all_errors.append("apply did not fully converge")

    for err in all_errors:
        print(f"✖ {err}", file=sys.stderr)
    if all_errors:
        return 1
    print("done")
    return 0


async def cmd_restore(
    client: hikari.api.RESTClient, config: Config, args: argparse.Namespace
) -> int:
    """Bring the guild back toward a backup snapshot (never deletes)."""
    try:
        snapshot = executor.load_snapshot(args.snapshot)
    except (OSError, ValueError) as err:
        print(f"error: cannot read snapshot: {err}", file=sys.stderr)
        return 1
    guild = await require_guild(client, config)
    if guild is None:
        return 1
    channels = await executor.snapshot_guild(client, config.guild_id)
    try:
        manifest = parse(render_manifest(snapshot))
    except ManifestError as err:
        print(
            f"error: snapshot is not renderable as a manifest: {err}",
            file=sys.stderr,
        )
        return 1
    except (KeyError, TypeError, ValueError) as err:
        print(
            f"error: snapshot has an invalid shape: {err}",
            file=sys.stderr,
        )
        return 1
    plan = build_plan(manifest, channels, delete=False)
    print(plan.render())
    if plan.is_clean():
        print("already matches the snapshot")
        return 0
    if not confirm(args):
        print("aborted")
        return 1
    backup = executor.backup_path(CHANNELS_BACKUP_DIR)
    executor.save_snapshot(backup, channels)
    print(f"backup: {backup}")
    result = await executor.apply_plan(
        client, config.guild_id, plan, delete=False
    )
    for err in result.errors:
        print(f"✖ {err}", file=sys.stderr)
    if result.errors:
        return 1
    print("done")
    return 0


# -- helpers (lower-level; used by the handlers above) -----------------------


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file + rename.

    A concurrent edit between the read at command start and this write
    can't corrupt the file — the rename is atomic on POSIX.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _add_file_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("channels.manifest"),
        help="manifest path (default: channels.manifest)",
    )


def _add_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope-below",
        metavar="CATEGORY",
        default=None,
        help="only manage the [CATEGORY] group and everything after it "
        "(groups above are kept as-is)",
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
        help="also delete channels not listed in the manifest",
    )


def _add_restore_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )


async def _plan(
    client: hikari.api.RESTClient,
    config: Config,
    args: argparse.Namespace,
    *,
    delete: bool,
) -> Plan | None:
    manifest = load_manifest(args.file)
    if manifest is None:
        return None
    return await _plan_from(client, config, manifest, args, delete=delete)


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
    name="channels",
    help="manage the channel manifest (export/diff/check/apply/restore)",
    common_args=(_add_file_args, _add_scope_args),
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
