#!/bin/env python
"""Check databases for schema drift against the Python-defined DDL.

Read-only: the databases are opened with ``mode=ro``, so this is safe to
point at the live production file. For each database it answers three
questions:

- **Would the bot boot?** The boot guard (``Database.verify_schema``)
  only requires the tables of *loaded* plugins, so a missing table that
  belongs to a disabled plugin is not a boot blocker.
- **What deviates from the full code DDL?** Core plus every plugin,
  enabled or not — the shape the code expects today.
- **Is the deviation accounted for?** Either a pending migration in
  ``scripts/migrations/`` that names the table, a benign additive table
  of a disabled plugin, or genuinely uncovered drift that needs a new
  script (see ``docs/how-do-i/add-a-migration.md``).

Usage::

    python scripts/schema_check.py                    # data/cazzubot-dev.db
    python scripts/schema_check.py data/cazzubot-dev.db
    python scripts/schema_check.py /mnt/tmp/CazzuBot/data/cazzubot.db
    python scripts/schema_check.py --simulate         # also dry-apply pending

``--simulate`` copies each database to a temp file, applies every pending
migration there through the shared harness (``run_one``), and re-checks:
it answers "would the existing migrations leave us clean?" without
touching the original.

Exit codes: 0 no drift, 1 drift covered by pending migrations (run
``scripts/migrate.py``), 2 uncovered drift (write a migration).

Call graph: ``main`` → ``check_db`` per path → ``core.db._schema_diff``
(deliberately the exact comparison the boot guard runs, so this checker
can never disagree with it) plus the ``MIGRATIONS`` registry for coverage;
``_simulate`` replays ``run_one`` on a temp copy.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from urllib.parse import quote

import aiosqlite

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import assets, inventory, scheduler, settings, statuses  # noqa: E402

# The guard's own comparator (private by design): reusing it means this
# checker can never disagree with the boot-time schema guard.
from core.db import (  # noqa: E402
    _schema_diff,  # pyright: ignore[reportPrivateUsage]
)
from core.plugin import Plugin, discover_plugins  # noqa: E402
from scripts.migrations import MIGRATIONS  # noqa: E402
from scripts.migrations.common import Migration, run_one  # noqa: E402

DEFAULT_DB = "data/cazzubot-dev.db"

# Exit codes (see the module docstring).
CLEAN = 0
COVERED = 1
UNCOVERED = 2

# Core-owned DDL, in the order CazzuBot._on_starting collects it.
CORE_SCHEMA: list[str] = [
    *settings.Settings.schema,
    *scheduler.Scheduler.schema,
    *assets.Assets.schema,
    *inventory.Inventory.schema,
    *statuses.Statuses.schema,
]

_TABLE_RE = re.compile(
    r"""CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"?(\w+)"?""",
    re.IGNORECASE,
)
_PROBLEM_TABLE_RE = re.compile(r"table '([^']+)'")


# -- model ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    """One drift problem plus how (or whether) it is accounted for.

    ``kind`` is ``covered`` (a pending migration names the table),
    ``benign`` (additive table of a disabled plugin) or ``uncovered``
    (needs a new migration).
    """

    text: str
    table: str | None
    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class Report:
    """Everything ``check_db`` learned about one database."""

    path: Path
    disk_tables: list[str]
    defined_tables: list[str]
    extra_tables: list[str]
    loaded: list[str]
    disabled: list[str]
    guard_problems: list[str]
    full_problems: list[str]
    findings: list[Finding]
    pending: list[str]
    warnings: list[str]
    simulated: list[Finding] | None
    simulate_failed: bool


# -- per-database check -----------------------------------------------------


async def check_db(path: Path, *, simulate: bool = False) -> Report:
    """Compare one database against the code DDL (never writes to it)."""
    uri, immutable = _readonly_uri(path)
    plugins = discover_plugins(str(ROOT / "plugins"))
    loaded, disabled = _partition_plugins(uri, plugins)
    defined = CORE_SCHEMA + [s for p in plugins for s in p.schema]
    guard_ddl = CORE_SCHEMA + [s for p in loaded for s in p.schema]
    owners = _table_owners(plugins)
    defined_tables = sorted(owners)

    warnings: list[str] = []
    if immutable:
        warnings.append(
            "opened with immutable=1 (the mount refuses read-only locks); "
            + "a concurrent writer would not be detected"
        )
    actual = await aiosqlite.connect(uri, uri=True)
    actual.row_factory = aiosqlite.Row
    try:
        disk_tables = sorted(await _table_names(actual))
        guard_problems = await _diff(actual, guard_ddl)
        full_problems = await _diff(actual, defined)
    finally:
        await actual.close()

    pending, pending_warnings = _pending(uri)
    warnings.extend(pending_warnings)
    loaded_names = [p.name for p in loaded]
    findings = [
        _classify(problem, pending, owners, loaded_names)
        for problem in full_problems
    ]

    simulated = None
    simulate_failed = False
    if simulate:
        simulated = await _simulate(
            uri,
            path.name,
            pending,
            defined,
            owners,
            loaded_names,
            warnings,
        )
        simulate_failed = simulated is None

    return Report(
        path=path,
        disk_tables=disk_tables,
        defined_tables=defined_tables,
        extra_tables=[t for t in disk_tables if t not in owners],
        loaded=loaded_names,
        disabled=[p.name for p in disabled],
        guard_problems=guard_problems,
        full_problems=full_problems,
        findings=findings,
        pending=[m.id for m in pending],
        warnings=warnings,
        simulated=simulated,
        simulate_failed=simulate_failed,
    )


def _classify(
    problem: str,
    pending: Sequence[Migration],
    owners: dict[str, str],
    loaded: Sequence[str],
) -> Finding:
    """Attach one problem to its pending migration or call it uncovered.

    Coverage is a name heuristic — a pending migration that mentions the
    table in its id or doc line is assumed to fix it; ``--simulate`` is
    the authoritative answer because it actually replays the migrations.
    """
    match = _PROBLEM_TABLE_RE.search(problem)
    if match is None:
        return Finding(
            problem, None, "uncovered", "not attributable to a table"
        )
    table = match.group(1)
    pattern = re.compile(rf"\b{re.escape(table)}\b", re.IGNORECASE)
    for migration in pending:
        if pattern.search(f"{migration.id} {migration.doc}"):
            return Finding(
                problem, table, "covered", f"pending {migration.id}"
            )
    owner = owners.get(table)
    if owner is not None and owner != "core" and owner not in loaded:
        return Finding(
            problem,
            table,
            "benign",
            f"table of disabled plugin {owner!r} "
            + "(created when the plugin is enabled)",
        )
    return Finding(
        problem, table, "uncovered", "no pending migration covers it"
    )


async def _simulate(
    uri: str,
    name: str,
    pending: Sequence[Migration],
    defined: Sequence[str],
    owners: dict[str, str],
    loaded: Sequence[str],
    warnings: list[str],
) -> list[Finding] | None:
    """Apply pending migrations to a temp copy, then re-check full DDL.

    ``None`` means the replay itself failed (a warning says why) — the
    caller must not read that as "the migrations leave the DB clean".
    """
    if not pending:
        return []
    with tempfile.TemporaryDirectory(prefix="schema-check-") as tmp:
        copy = Path(tmp) / name
        src = sqlite3.connect(uri, uri=True)
        dst = sqlite3.connect(copy)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        conn = sqlite3.connect(copy)
        current = pending[0]
        try:
            with redirect_stdout(StringIO()):
                for current in pending:
                    run_one(
                        current,
                        conn,
                        commit=True,
                        backup_dir=tmp,
                        db_path=copy,
                    )
        except Exception as err:
            warnings.append(f"simulate failed on {current.id}: {err!r}")
            return None
        finally:
            conn.close()
        actual = await aiosqlite.connect(_uri(copy), uri=True)
        actual.row_factory = aiosqlite.Row
        try:
            problems = await _diff(actual, defined)
        finally:
            await actual.close()
    return [_classify(problem, [], owners, loaded) for problem in problems]


# -- helpers ----------------------------------------------------------------


def _uri(path: Path, *, immutable: bool = False) -> str:
    """Read-only SQLite URI for ``path``."""
    suffix = "&immutable=1" if immutable else ""
    return f"file:{quote(str(path))}?mode=ro{suffix}"


def _readonly_uri(path: Path) -> tuple[str, bool]:
    """First read-only URI that actually opens, plus whether it needed
    ``immutable=1``.

    Read-only sshfs mounts refuse ``mode=ro`` (SQLite cannot take locks);
    ``immutable=1`` skips locking and trusts the file not to change under
    us, which is what makes checking the production DB possible at all.
    """
    for immutable in (False, True):
        uri = _uri(path, immutable=immutable)
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.execute("SELECT 1").fetchone()
        except sqlite3.Error:
            continue
        finally:
            if conn is not None:
                conn.close()
        return uri, immutable
    return _uri(path), False


async def _table_names(conn: aiosqlite.Connection) -> set[str]:
    """User table names (sqlite-internal tables excluded)."""
    rows = await conn.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )
    return {r["name"] for r in rows if not r["name"].startswith("sqlite_")}


async def _diff(
    actual: aiosqlite.Connection, statements: Sequence[str]
) -> list[str]:
    """Drift of ``actual`` against a throwaway reference built from DDL."""
    ref = await aiosqlite.connect(":memory:")
    ref.row_factory = aiosqlite.Row
    try:
        for statement in statements:
            await ref.execute(statement)
        return await _schema_diff(actual, ref)
    finally:
        await ref.close()


def _table_owners(plugins: Sequence[Plugin]) -> dict[str, str]:
    """Map every code-defined table to the plugin (or ``core``) owning it."""
    owners: dict[str, str] = {}
    for statement in CORE_SCHEMA:
        match = _TABLE_RE.search(statement)
        if match:
            owners.setdefault(match.group(1), "core")
    for plugin in plugins:
        for statement in plugin.schema:
            match = _TABLE_RE.search(statement)
            if match:
                owners.setdefault(match.group(1), plugin.name)
    return owners


def _partition_plugins(
    uri: str, plugins: Sequence[Plugin]
) -> tuple[list[Plugin], list[Plugin]]:
    """Split plugins into loaded/disabled exactly as the bot would."""
    overrides = _settings_overrides(uri)
    loaded: list[Plugin] = []
    disabled: list[Plugin] = []
    for plugin in plugins:
        value = overrides.get(
            f"plugin.enabled.{plugin.name}", plugin.enabled
        )
        (loaded if value else disabled).append(plugin)
    return loaded, disabled


def _settings_overrides(uri: str) -> dict[str, object]:
    """``plugin.enabled.*`` settings, or ``{}`` when unreadable."""
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            "SELECT key, value FROM settings "
            + "WHERE key LIKE 'plugin.enabled.%'"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    overrides: dict[str, object] = {}
    for key, raw in rows:
        try:
            overrides[key] = json.loads(raw)
        except TypeError, ValueError:
            continue
    return overrides


def _pending(uri: str) -> tuple[list[Migration], list[str]]:
    """Pending migrations for the database at ``uri`` plus gate errors."""
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as err:
        return [], [f"cannot read migrations state: {err!r}"]
    pending: list[Migration] = []
    warnings: list[str] = []
    try:
        for migration in MIGRATIONS:
            try:
                if migration.needs(conn):
                    pending.append(migration)
            except Exception as err:
                warnings.append(f"{migration.id}.needs() failed: {err!r}")
    finally:
        conn.close()
    return pending, warnings


def exit_code(report: Report) -> int:
    """0 clean, 1 covered drift, 2 uncovered or unprovable drift."""
    if report.simulate_failed:
        return UNCOVERED  # coverage could not be proven
    findings = list(report.findings)
    if report.simulated is not None:
        findings += report.simulated
    if any(f.kind == "uncovered" for f in findings):
        return UNCOVERED
    return COVERED if findings else CLEAN


# -- reporting --------------------------------------------------------------


def _print_report(report: Report) -> None:
    """Print one database's full verdict."""
    print(f"== {report.path}")
    print(
        f"   on disk: {len(report.disk_tables)} tables"
        + f" | code DDL: {len(report.defined_tables)} tables"
        + f" | extra on disk: {', '.join(report.extra_tables) or 'none'}"
    )
    print(
        f"   loaded plugins ({len(report.loaded)}): "
        + (", ".join(report.loaded) or "none")
    )
    print(
        f"   disabled plugins ({len(report.disabled)}): "
        + (", ".join(report.disabled) or "none")
    )
    guard = (
        "PASS"
        if not report.guard_problems
        else f"FAIL — {len(report.guard_problems)} problem(s)"
    )
    print(f"   boot guard (loaded plugins only): {guard}")
    print(f"   full code DDL drift: {len(report.findings)} problem(s)")
    for finding in report.findings:
        _print_problem(finding)
    if report.simulate_failed:
        print("   simulate: FAILED — see the warning below")
    elif report.simulated is not None:
        if not report.pending:
            print("   simulate: no pending migrations to apply")
        elif not report.simulated:
            print(
                "   simulate: applying pending migrations leaves the DB "
                + "clean"
            )
        else:
            print(
                "   simulate: pending migrations still leave "
                + f"{len(report.simulated)} problem(s):"
            )
            for finding in report.simulated:
                _print_problem(finding)
    for warning in report.warnings:
        print(f"   warning: {warning}")
    print(
        "   pending migrations: " + (", ".join(report.pending) or "none")
    )
    code = exit_code(report)
    if code == CLEAN:
        print("   verdict: no drift")
    elif code == COVERED:
        print(
            "   verdict: drift is covered by pending migrations — run "
            + f"python scripts/migrate.py --db {report.path} --commit"
        )
    else:
        print(
            "   verdict: uncovered drift — write a migration "
            + "(docs/how-do-i/add-a-migration.md)"
        )
    print()


def _print_problem(finding: Finding) -> None:
    """Print one finding, indenting the detail lines of multi-line text."""
    lines = finding.text.splitlines()
    print(f"     - {lines[0]}")
    for extra in lines[1:]:
        print(f"       {extra}")
    marker = {
        "covered": f"covered by {finding.detail}",
        "benign": f"benign — {finding.detail}",
        "uncovered": f"UNCOVERED — {finding.detail}",
    }[finding.kind]
    print(f"       → {marker}")


# -- CLI --------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Check each database and return the worst exit code (CLI entry)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "db",
        nargs="*",
        default=[DEFAULT_DB],
        help=f"database file(s) to check (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="apply pending migrations to a temp copy and re-check",
    )
    args = parser.parse_args(argv)

    worst = CLEAN
    for raw in args.db or [DEFAULT_DB]:
        path = Path(raw)
        if not path.exists():
            print(f"== {path}\n   verdict: no such file\n")
            worst = max(worst, UNCOVERED)
            continue
        report = asyncio.run(check_db(path, simulate=args.simulate))
        _print_report(report)
        worst = max(worst, exit_code(report))
    return worst


if __name__ == "__main__":
    sys.exit(main())
