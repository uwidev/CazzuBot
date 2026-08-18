"""Admin-CLI verbs shared by the roles/channels manifest domains.

Both domains expose the same five verbs (export/diff/check/apply/restore)
and differ only in engine wiring: which snapshot builder, manifest
renderer, parser, plan builder and apply loop to call, plus an optional
pre-apply guard (roles: blocked reorder; channels: unsupported type
changes). ``ManifestDomain`` bundles that wiring; the verbs here run
either domain.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import hikari

from cazzubot.cli.core import confirm, export_stamp, require_guild
from cazzubot.config import Config
from cazzubot.manifest.executor import (
    backup_path,
    load_snapshot,
    save_snapshot,
)
from cazzubot.manifest.lines import ManifestError, rewrite_renames


@dataclass(frozen=True, slots=True)
class ManifestDomain:
    """The wiring one manifest domain provides to the shared verbs."""

    name: str  # backup file prefix ("roles" / "channels")
    backup_dir: Path
    snapshot: Callable[[hikari.api.RESTClient, int], Awaitable[list[Any]]]
    render: Callable[[list[Any], str, str], str]  # (snapshot, source, exported)
    parse: Callable[[str], Any]
    plan_from: Callable[..., Awaitable[Any | None]]
    apply: Callable[..., Awaitable[Any]]
    guard: Callable[[Any], str | None] | None = None  # pre-apply block message


async def run_export(
    client: hikari.api.RESTClient,
    config: Config,
    args: argparse.Namespace,
    domain: ManifestDomain,
) -> int:
    """Write a fresh manifest from the live guild."""
    guild = await require_guild(client, config)
    if guild is None:
        return 1
    snapshot = await domain.snapshot(client, config.guild_id)
    text = domain.render(
        snapshot,
        f"live guild {guild.name}",
        export_stamp(),
    )
    args.file.write_text(text, encoding="utf-8")
    print(f"wrote {args.file} ({text.count(chr(10))} lines)")
    return 0


async def run_diff(
    client: hikari.api.RESTClient,
    config: Config,
    args: argparse.Namespace,
    domain: ManifestDomain,
) -> int:
    """Show the plan; exit 1 when the guild drifts."""
    plan = await _plan(client, config, args, domain, delete=args.delete)
    if plan is None:
        return 1
    print(plan.render())
    return 0 if plan.is_clean() else 1


async def run_check(
    client: hikari.api.RESTClient,
    config: Config,
    args: argparse.Namespace,
    domain: ManifestDomain,
) -> int:
    """Hook-friendly drift check: exit 1 on drift, prints a summary."""
    plan = await _plan(client, config, args, domain, delete=False)
    if plan is None:
        return 1
    if not plan.is_clean():
        print(f"DRIFT: {plan.summary()}")
        print(plan.render())
        return 1
    print("clean")
    return 0


async def run_apply(
    client: hikari.api.RESTClient,
    config: Config,
    args: argparse.Namespace,
    domain: ManifestDomain,
) -> int:
    """Reconcile the guild to the file, with backup + confirmation."""
    loaded = load_manifest_text(args.file, domain.parse)
    if loaded is None:
        return 1
    manifest_text, manifest = loaded
    plan = await domain.plan_from(
        client, config, manifest, args, delete=args.delete
    )
    if plan is None:
        return 1
    if plan.is_clean():
        print("clean — nothing to do")
        return 0
    print(plan.render())
    if domain.guard is not None:
        block = domain.guard(plan)
        if block is not None:
            print(f"error: {block}", file=sys.stderr)
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
    if guild is None:
        return 1
    backup = backup_path(domain.backup_dir, domain.name)
    save_snapshot(backup, await domain.snapshot(client, config.guild_id))
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
        result = await domain.apply(
            client, config.guild_id, current_plan, delete=args.delete
        )
        all_errors.extend(result.errors)
        applied = list(result.applied_renames)
        applied.extend(current_plan.cleanup_renames)
        if applied:
            renames = [(op.line, op.old, op.new) for op in applied]
            rewritten = rewrite_renames(manifest_text, renames)
            try:
                manifest = domain.parse(rewritten)
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
        current_plan = await domain.plan_from(
            client, config, manifest, args, delete=args.delete
        )
        if current_plan is None:
            all_errors.append("re-plan after apply failed")
            break
        if not current_plan.needs_apply:
            break  # the guild matches the manifest
    else:
        print(
            "warning: apply did not fully converge — remaining drift:",
            file=sys.stderr,
        )
        print(current_plan.render(), file=sys.stderr)
        all_errors.append("apply did not fully converge")

    exit_code = _report_errors(all_errors)
    if not all_errors:
        print("done")
    return exit_code


async def run_restore(
    client: hikari.api.RESTClient,
    config: Config,
    args: argparse.Namespace,
    domain: ManifestDomain,
) -> int:
    """Bring the guild back toward a backup snapshot (never deletes)."""
    try:
        snapshot = load_snapshot(args.snapshot)
    except (OSError, ValueError) as err:
        print(f"error: cannot read snapshot: {err}", file=sys.stderr)
        return 1
    guild = await require_guild(client, config)
    if guild is None:
        return 1
    live = await domain.snapshot(client, config.guild_id)
    try:
        manifest = domain.parse(domain.render(snapshot, "", ""))
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
    plan = await domain.plan_from(client, config, manifest, args, delete=False)
    if plan is None:
        return 1
    print(plan.render())
    if plan.is_clean():
        print("already matches the snapshot")
        return 0
    if not confirm(args):
        print("aborted")
        return 1
    backup = backup_path(domain.backup_dir, domain.name)
    save_snapshot(backup, live)
    print(f"backup: {backup}")
    result = await domain.apply(
        client, config.guild_id, plan, delete=False
    )
    exit_code = _report_errors(result.errors)
    if not result.errors:
        print("done")
    return exit_code


# -- helpers -----------------------------------------------------------------


async def _plan(
    client: hikari.api.RESTClient,
    config: Config,
    args: argparse.Namespace,
    domain: ManifestDomain,
    *,
    delete: bool,
) -> Any | None:
    manifest = load_manifest(args.file, domain.parse)
    if manifest is None:
        return None
    return await domain.plan_from(
        client, config, manifest, args, delete=delete
    )


def load_manifest(path: Path, parse: Callable[[str], Any]) -> Any | None:
    """Read + parse the manifest; print issues and return None on failure."""
    loaded = load_manifest_text(path, parse)
    return None if loaded is None else loaded[1]


def load_manifest_text(
    path: Path, parse: Callable[[str], Any]
) -> tuple[str, Any] | None:
    """Like :func:`load_manifest`, but also returns the raw text.

    The text is needed by verbs that rewrite the manifest in place
    (``run_apply`` feeds it back through ``rewrite_renames``).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        print(f"error: cannot read {path}: {err}", file=sys.stderr)
        return None
    try:
        return text, parse(text)
    except ManifestError as err:
        for issue in err.issues:
            print(f"{path}:{issue}", file=sys.stderr)
        return None


def _report_errors(errors: list[str]) -> int:
    """Print each error to stderr and return the process exit code."""
    for err in errors:
        print(f"✖ {err}", file=sys.stderr)
    return 1 if errors else 0


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file + rename.

    A concurrent edit between the read at command start and this write
    can't corrupt the file — the rename is atomic on POSIX.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# -- argparse helpers (identical across the two domains) ---------------------


def add_file_args(default: Path) -> Callable[[argparse.ArgumentParser], None]:
    """Build the ``--file`` argument group bound to ``default``."""

    def _add(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--file",
            type=Path,
            default=default,
            help=f"manifest path (default: {default.name})",
        )

    return _add


def add_diff_args(parser: argparse.ArgumentParser) -> None:
    """Add the diff preview's ``--delete`` flag."""
    parser.add_argument(
        "--delete",
        action="store_true",
        help="include delete candidates in the preview",
    )


def add_apply_args(parser: argparse.ArgumentParser) -> None:
    """Add the apply command's ``--yes``/``--delete`` flags."""
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="also delete items not listed in the manifest",
    )


def add_restore_args(parser: argparse.ArgumentParser) -> None:
    """Add the restore command's ``snapshot`` path and ``--yes`` flag."""
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
