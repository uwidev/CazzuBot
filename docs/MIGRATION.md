# CazzuBot v1 ↔ v2 database migration (PostgreSQL ↔ SQLite)

The v2 rewrite (`rewrite` branch) is SQLite-only — one file at
`data/cazzubot.db`, no PostgreSQL. This document is the ops protocol for
switching the live production data over when you cut the rewrite branch into
production. The per-table transform spec lives in
[`scripts/migration/MAPPING.md`](../scripts/migration/MAPPING.md); the
tools are:

| Tool | Purpose |
|---|---|
| `scripts/migrate_pg_to_sqlite.py` | Reads the live PostgreSQL **read-only**, writes a fresh SQLite DB |
| `scripts/verify_migration.py` | Full per-uid parity check of the migrated DB against the live PostgreSQL |
| `scripts/boot_check_migrated.py` | Boots the v2 stack against the swapped-in DB (no Discord connection) and asserts the expected first-boot effects |
| `scripts/sqlite_to_pg.py` | Reverse direction: refills the frozen v1 PostgreSQL from the SQLite file at rollback time (exp, frog, counter tables) |

All four are one-off operational scripts — they are not part of the bot
runtime. The only extra dependency (`asyncpg`) comes from the `migration`
dependency group, activated per invocation with `--group migration`.

## Prerequisites

- You are on the `rewrite` branch (the scripts live there).
- PostgreSQL is reachable from the machine running the migration.
  Defaults: `192.168.1.3:5432`, database `main`, user `cazzubot`, **no SSL**.
- Credentials go in the environment — never on the command line:

  ```bash
  export PGPASSWORD='...'
  ```

- `GUILD_ID` is set in `.env` (or pass `--gid`). The migration keeps only that
  one guild's rows — v2 serves a single guild and drops all `gid` columns.

## Protocol — 3 steps

### 1. Migrate (read-only on PostgreSQL)

```bash
PGPASSWORD=... uv run --group migration python scripts/migrate_pg_to_sqlite.py
```

- Writes `data/cazzubot.migrated.db` (override with `--out`). It **never**
  touches the source PostgreSQL and never touches `data/cazzubot.db` — the
  current SQLite file is left untouched until step 3.
- Re-runnable: the output file is replaced at start, so re-running picks up
  everything that changed on PostgreSQL since the previous run. Nothing is
  lost by waiting.
- Prints a per-table report (source vs. inserted rows) plus the judgment-call
  counters (see below) and runs a first batch of post-load checks.

### 2. Verify (read-only on both sides)

```bash
PGPASSWORD=... uv run --group migration python scripts/verify_migration.py
```

Compares every table per-uid against the live PostgreSQL: `member_exp`
(lifetime, msg_cnt), `member_exp_log` (row count, sum of exp), `member_frog`
(normal, frozen, capture), `member_frog_log` (row count, sum of `waited_for`),
exact row equality on the small tables, four seasonal leaderboards through
v2's own query path, the v2 resync functions on a throwaway copy, settings
round-trip, and poll integrity after the item-id renumbering. Run this
**before** swapping; it exits non-zero on any mismatch.

### 3. Swap in and boot

```bash
cp data/cazzubot.db "data/cazzubot.db.bak-$(date +%s)"
mv data/cazzubot.migrated.db data/cazzubot.db
uv run python main.py -d   # or -p once you are actually ready
```

Keep PostgreSQL up until the new bot has booted and you have verified
production — it is the ultimate rollback.

## First-boot effects (read before swapping)

The migrated DB is a faithful snapshot, but the v2 boot sequence intentionally
changes a few things on the **first** start:

1. **Quarterly frog freeze.** v2's `QuarterlyPlugin.on_load` compares
   `quarterly.last_quarterly` against the current quarter. If the value is
   stale (as of 2026 the production value is `2025-12-10`, i.e. several
   quarters behind), the first boot **moves every member's `normal` frogs to
   `frozen`** to catch up the missed quarters, then records the current
   quarter. If you want to preserve balances instead, set the setting *after*
   migrating and *before* booting:

   ```bash
   # e.g. current quarter is 2026-Q3: suppresses the catch-up freeze,
   # next real freeze happens at the next quarter boundary
   uv run python - <<'EOF'
   import asyncio
   from cazzubot.db import Database
   from cazzubot.settings import Settings

   async def main():
       db = Database("data/cazzubot.db")
       await db.connect()
       await Settings(db).set("quarterly.last_quarterly", "2026-07-01T00:00:00+00:00")
       await db.close()

   asyncio.run(main())
   EOF
   ```

2. **Frog spawn tasks.** Pending `frog` spawn tasks are not migrated (v1's
   `task` rows are dropped); v2's frog plugin re-queues them from the
   `frog_spawn` table at boot. Expect 4 `frog`-tagged rows in `tasks` after
   the first boot.

3. **Daily reset.** Does *not* force on boot as long as `daily.last_daily` is
   newer than 24 h (the migrated value is the day the snapshot was taken).

## What the migration does (summary)

- Filters every table to the target guild and drops `gid`.
- Preserves `poll.id` and maps `modlog.case_id` → `id`; **renumbers**
  `poll_item` ids to be globally unique and rewrites `poll_vote.iid` through
  the same mapping (v1 item ids are only unique per poll).
- Converts `timestamptz` → ISO-8601 UTC strings, `bool` → `0/1`,
  `json`/`int[]` → JSON text, enums → plain text (values match v2).
- 5,680 `member_exp_log` rows with `at = NULL` (the historical bulk exp
  import, one row per user) get the sentinel timestamp
  `1970-01-01T00:00:00+00:00`: lossless — they still count in lifetime sums
  and resyncs, but are excluded from every seasonal window.
- `member_frog.deprecated_normal` (the retired pre-split `frog` column) is
  archived into `_archive_member_frog_deprecated_normal` (1,371 rows) instead
  of dropped.
- 3 `member_frog_log` rows with `gid = NULL` are attributed to the target
  guild; the lone `exp_log` row with source `'frozen'` is kept verbatim (v2
  never reads `source`).
- Config tables (`guild`, `level`, `rank`, `frog`, `welcome`, `internal`) are
  ported into the v2 `settings` key-value store (`inktober.cid`,
  `level.message`/`level.quiet`, `rank.{mode}.*`, `frog.*`, `welcome.*`,
  `daily.last_daily`, `quarterly.last_quarterly`).
- `user` / `member` / `channel` / `role` tables are skipped — v2 creates
  those rows on demand.

Every judgment call is printed in the tool's report, so nothing disappears
silently.

## Rollback

- Restore the pre-swap backup:
  `mv data/cazzubot.db.bak-<timestamp> data/cazzubot.db`.
- Or simply re-run the protocol — the PostgreSQL source is never written to,
  so a fresh migration is always possible while it is up.

## Rolling back to v1 (SQLite → PostgreSQL)

If the v2 trial fails and you want v1 back, the v1 PostgreSQL database must
be refilled with what v2 recorded during the trial — v1 is frozen the whole
time v2 runs, so its tables hold only the cutover state.
`scripts/sqlite_to_pg.py` carries the exp, frog, and counter data back,
which are the only tables that need to survive a rollback (deliberate scope
decision; modlog, polls, rank_threshold, settings and tasks keep their
cutover state on PostgreSQL, which is exactly what v1 expects).

```bash
PGPASSWORD=... uv run --group migration python scripts/sqlite_to_pg.py
```

- Defaults to a **dry run** (plan only, nothing written). Pass `--commit`.
- Replace-per-guild: deletes the target guild's rows and inserts the full
  SQLite contents in one transaction; re-runnable (idempotent). The SQLite
  file is a superset of the guild's PostgreSQL rows because v1 never wrote
  during the trial, so this is lossless for the ported tables.
- Backfills the `user`/`channel`/`guild` FK-support rows first (v1 has real
  FKs — trial-era members/channels would otherwise violate them), restores
  `member_frog.deprecated_normal` from the archive table, and writes the
  5,680 sentinel exp-log timestamps back as NULL (v1's original shape).
- A built-in post-write per-uid parity check runs **before** commit — any
  write-path mismatch (type/constraint/enum errors included) rolls the whole
  transaction back, leaving PostgreSQL untouched.
- Stop the v2 bot first so the SQLite snapshot is unambiguous.

Ported: `member_exp`, `member_exp_log`, `member_frog`, `member_frog_log`,
`frog_spawn`, `counter`. If the SQLite `counter` table predates the count
column (legacy mid-only shape), only counter *presence* is ported — v1's
existing counts are never touched and trial-created mids get the v1 default
(0). Not ported: modlog entries created during the trial exist only
in the SQLite `modlog` table — if a tempban/mute was issued mid-trial it
won't be enforced by v1 unless v1 re-checks `modlog.expires_on` at boot.

## Audit trail from the initial migration (2026-08-05)

- Migration: 7,163 `member_exp`, 1,491,248 `member_exp_log`, 2,146
  `member_frog`, 541,990 `member_frog_log`, 4 `frog_spawn`, 19
  `rank_threshold`, 1 `modlog`, 1 `counter`, 14 `poll`, 295 `poll_item`,
  346 `poll_vote`; 1,371 `deprecated_normal` rows archived; 19 settings keys.
- Verification: zero mismatches everywhere; `sync_with_exp_logs` zero drift;
  the only `sync_with_frog_logs` drift is the owner's 3 attributed NULL-gid
  captures (5,330 → 5,333, expected).
- First boot: quarterly freeze applied (normal 34,052 → 0, frozen 80,658 →
  114,710), 4 frog spawn tasks queued, daily reset did not force.
- Backups: `data/cazzubot.db.bak-20260805-094024` (previous dev DB) and
  `data/cazzubot.db.migrated.pristine` (migrated DB before the first boot).
