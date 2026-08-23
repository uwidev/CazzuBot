# How do I... add a database migration

Stateful (data) migrations live in `scripts/migrations/` and run through
the shared harness in `scripts/migrate.py`. You only write the transform
— the CLI, dry-run/commit contract, backups, and idempotence gate are
shared (`scripts/migrations/common.py`).

## When do I need one?

Schema adds/changes that touch **existing rows** typically need a
migration (e.g. a new column with a default, a rebuild because a column
default changed, re-keying stored values). Purely additive `CREATE TABLE
IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` changes don't — restarting
the bot applies those (`docs/add-a-schema.md`).

Migration script heuristics:

- Run **while the bot is stopped**: the boot-time schema guard refuses to
  start on a legacy shape, and these scripts target the live file.
- Dry run by default; `--commit` writes. The database is backed up to
  `<backup-dir>/<id>_backup-<timestamp>.db` before any mutation.
- Idempotent: the `needs` gate is False once the legacy shape is gone, so
  re-running is a no-op.

## 1. Write the module

`scripts/migrations/<name>.py` — one module per migration, exposing the
four functions plus a `MIGRATION` registry entry:

```python
from scripts.migrations.common import Migration


@dataclass(frozen=True, slots=True)
class MyPlan:
    rows: int  # what the dry-run report carries


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True while the legacy shape is present (the idempotence gate)."""


def plan(conn: sqlite3.Connection) -> MyPlan:
    """Read-only counts of what migrate() would do."""


def migrate(conn: sqlite3.Connection) -> MyPlan:
    """Apply the change in ONE transaction (BEGIN/COMMIT, rollback on error)."""


MIGRATION = Migration(
    id="006_my_change",   # next number in scripts/migrations/__init__.py
    doc="one-line description for --list",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: f"one-line dry-run report ({p.rows} row(s))",
    migrate=migrate,
    # verify=lambda conn: ...  # optional post-commit check
)
```

## 2. Register it

Append the module's `MIGRATION` to `MIGRATIONS` in
`scripts/migrations/__init__.py` with the next id (`007_...`, `008_...`).
Order there is the run order.

## 3. Rules (learned from the existing five)

- **DDL parity is the real acceptance test.** Migrated tables must match
  the plugin's Python DDL exactly — column order, defaults, indexes, the
  `AUTOINCREMENT` keyword. A default change means a table **rebuild**
  (create `..._new`, copy with `CASE` rewrites, drop, rename) — a plain
  row rewrite leaves the old default and fails the boot guard. See
  `scripts/migrations/frog_species_key.py` for the pattern.
- **Mirror the DDL from the codebase**, don't retype it from memory
  (`plugins/counter/db.py`'s `SCHEMA` is imported by
  `scripts/migrations/counter_events.py`).
- **Read by column position in module helpers** (not `row["name"]`) so
  the functions work on plain test connections too.
- **Verify inside the transaction when possible** — a parity check before
  commit rolls the whole migration back on mismatch (counter_events does
  this).
- **Backups before mutation happen in the harness** — don't add your own.

## 4. Tests

- Unit-test `needs` / `plan` / `migrate` against a temp legacy DB —
  the harness contract in `tests/core/test_migration_runner.py` and the
  per-migration tests (e.g. `tests/core/test_migrate_frog_species.py`).
- Acceptance: migrate a temp legacy DB, then boot the bot
  (`CazzuBot` + `_on_starting`) so the **real** `verify_schema` guard
  runs, and read migrated data back through the plugin's db module
  (`test_migrate_frog_species.py` is the template).

## 5. Run it

```sh
python scripts/migrate.py --db data/cazzubot-prod.db --list   # what's pending
python scripts/migrate.py --db data/cazzubot-prod.db          # dry run
python scripts/migrate.py --db data/cazzubot-prod.db --commit # apply
python scripts/migrate.py --only 006_my_change --commit       # one migration
```

The old entry points still work as thin wrappers
(`python scripts/migrate_<name>.py`).