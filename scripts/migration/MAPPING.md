# CazzuBot v1 (PostgreSQL) → v2 (SQLite) migration mapping

One-time migration of the live v1 PostgreSQL database into the v2 SQLite
database. Implemented by `scripts/migrate_pg_to_sqlite.py` (see below for
invocation); this document is the authoritative transform spec. The full ops
protocol (prereqs, migrate → verify → swap, first-boot effects, rollback)
lives in [`docs/MIGRATION.md`](../../docs/MIGRATION.md).

## Source

- PostgreSQL 16.13 at `192.168.1.3:5432`, database `main`, user `cazzubot`
  (password via env `PGPASSWORD`), no SSL.
- 22 tables; all reads are `SELECT`s, never mutating the source.
- Target guild (single guild): **`293796316193095690`** (= `GUILD_ID` in
  `.env`). A second guild (`408801760581386245`) exists and is filtered out —
  the v2 bot serves one guild only.

## Target

- Fresh SQLite file (default `data/cazzubot.migrated.db`), schema created from
  the **real** v2 DDL lists imported from the codebase, so it can never drift:
  - `cazzubot/settings.py` → `settings`
  - `cazzubot/scheduler.py` → `tasks`
  - `plugins/experience/db.py` → `member_exp`, `member_exp_log`
  - `plugins/frogs/db.py` → `member_frog`, `member_frog_log`, `frog_spawn`
  - `plugins/ranks/db.py` → `rank_threshold`
  - `plugins/mod/__init__.py` → `modlog`
  - `plugins/poll/__init__.py` → `poll`, `poll_item`, `poll_vote`
  - `plugins/counter/__init__.py` → `counter`
- Plus one archive table (not part of v2, ignored by the bot):
  `_archive_member_frog_deprecated_normal (uid, deprecated_normal)`.

## Global type conversions

| v1 (Postgres)             | v2 (SQLite)                            |
|---------------------------|----------------------------------------|
| `timestamptz`             | ISO-8601 string `dt.isoformat()` (UTC) |
| `bool`                    | `0` / `1` integer                      |
| `json` / `jsonb`          | JSON text via `cazzubot.db.dump_json`  |
| `int8[]` (`level.quiet`)  | JSON array text                        |
| enums (`*_enum`)          | plain text (values match v2, see below)|
| NULL on NOT NULL v2 cols  | coalesced + reported (see per-table)   |

Enum label sets match v2 exactly (`frog_type`: normal/frozen; `modlog_type`:
warn/mute/kick/tempban/ban; `modlog_status`: active/pardoned/deleted;
`window`: seasonal/lifetime; `welcome_mode`: pending/role;
`exp_log_source`: message/frog — plus one historical `'frozen'` row, kept
verbatim; v2 never reads `source`).

## Per-table mapping (target guild only)

### `member_exp` — 7,163 rows
- v1 `(uid, gid, lifetime, msg_cnt, cdr)` → v2 `(uid, lifetime, msg_cnt, cdr)`.
- Drop `gid`. `cdr` timestamptz → ISO string or NULL (v2 allows NULL).

### `member_exp_log` — 1,491,244 rows (largest table)
- v1 `(uid, gid, exp, at, source)` → v2 `(id auto, uid, exp, at, source)`.
- v1 has **no** `id`; v2 auto-assigns. `at` is `NOT NULL` in v2, but 5,680 v1
  rows have `at IS NULL` (verified: exactly one per uid — the bulk import of
  pre-Oct-2023 exp; `member_exp.lifetime` includes them, dated log sums do
  not). Insert them with sentinel **`1970-01-01T00:00:00+00:00`**:
  lossless (lifetime/`exp resync` keep v1 totals), and excluded from every
  seasonal window (`at >= start` filter), which matches their true nature.

### `member_frog` — 2,146 rows
- v1 `(gid, uid, deprecated_normal, frozen, capture, normal)` →
  v2 `(uid, normal, frozen, capture)`.
- `deprecated_normal` is the pre-split `frog` column, renamed out of service
  (current code only reads/writes `normal`/`frozen`; quarterly freeze never
  touches it). **Archived** into `_archive_member_frog_deprecated_normal`
  (rows where `deprecated_normal <> 0`, 1,371 rows) instead of dropped.
- NULL → 0 coalescing on `normal`/`frozen`/`capture`.

### `member_frog_log` — 541,986 rows
- v1 `(gid, uid, at, type, waited_for)` → v2 `(id auto, uid, type, at, waited_for)`.
- v1 has no `id`; v2 auto-assigns. 3 rows have `gid IS NULL` (owner's 2024
  captures): attributed to the target guild (uid is a member there) and
  reported. `waited_for` float may be NULL (v2 allows).

### `frog_spawn` — 4 rows
- v1 `(gid, cid, interval, persist, fuzzy)` → v2 `(cid, interval, persist, fuzzy)`.

### `rank_threshold` — 19 rows
- v1 `(gid, rid, threshold, mode)` → v2 `(rid, threshold, mode)`
  (v2 PK `(rid, mode)` — unique after gid filter).

### `modlog` — 1 row
- v1 `(gid, uid, case_id, log_type, given_on, status, expires_on, reason)` →
  v2 `(id, uid, log_type, given_on, status, expires_on, reason)`.
- `case_id` → `id` (value preserved; v2 uses the id as the case number).
  Timestamps → ISO or NULL.

### `counter` — 1 row
- v1 `(gid, mid, count)` → v2 `(mid, count)`.

### `poll` / `poll_item` / `poll_vote` — 14 / 295 / 346 rows
- Drop `gid`; **preserve `poll.id`** explicitly (v1 ids 1–14 are unique in the
  target guild) so nothing else shifts.
- `poll_item.id` in v1 is unique only per `(gid, pid)` — every poll numbers its
  items 1..N. v2 requires globally unique item ids (`poll_vote.iid` is a single
  column, PK `(pid, iid, uid)`). The tool **renumbers items** to fresh global
  ids in `(pid, id)` order and **rewrites every `poll_vote.iid`** through the
  same `(pid, old_id) -> new_id` mapping. Votes whose `(pid, iid)` had no item
  (verified: none) would be skipped and reported.
- `poll.open` bool → 0/1; `poll.description` NULL → `''` (v2 `NOT NULL`).
- `poll_item.description` exists in v1 but is NULL on all 295 rows; v2 has no
  such column — dropped, nothing lost.

### `tasks` (v1 `task`) — 0 rows migrated
- v1 `(id, tag varchar[], run_at, payload)`; all 4 pending rows are `['frog']`
  spawn tasks for exactly the 4 `frog_spawn` channels. v2's frog plugin
  **re-schedules spawns from `frog_spawn` at boot** (`factory.reset_frog_tasks`)
  — migrating both would double-schedule. Drop pending tasks, migrate
  `frog_spawn` only. (v1 `tag` is an array; v2 uses a plain string.)

### Config tables → `settings` (target guild rows only)

| v1 table      | v2 settings keys                                             |
|---------------|--------------------------------------------------------------|
| `guild`       | `inktober.cid` (mute_role NULL → not stored)                 |
| `level`       | `level.message` (JSON dict), `level.quiet` (JSON list)       |
| `rank`        | `rank.{mode}.message` / `.enabled` / `.keep_old` per mode row|
| `frog`        | `frog.message`, `frog.enabled`                               |
| `welcome`     | `welcome.enabled` / `.default_rid` / `.cid` / `.message` / `.mode` / `.monitor_rid` |
| `internal`    | `daily.last_daily`, `quarterly.last_quarterly` (ISO strings) |

All values stored through `cazzubot.db.dump_json` (JSON text), matching what
`Settings.set` produces. None-valued columns are skipped (absent ≡ None on
read).

## Skipped v1 tables

`user`, `member`, `channel`, `role` — v1 FK-support tables; v2 has no such
tables (`INSERT OR IGNORE` on demand). No data is lost: every uid/cid/rid in
the migrated tables is preserved as a plain integer.

## Judgment calls surfaced in the run report

1. 5,680 `member_exp_log` rows with `at = NULL` → sentinel (see above).
2. 1,371 `member_frog` rows with `deprecated_normal` → archived, not folded in.
3. 3 `member_frog_log` rows with `gid = NULL` → attributed to target guild.
4. 1 `member_exp_log` row with source `'frozen'` → kept verbatim.
5. 1 `member_frog` row with only-deprecated data (normal=frozen=capture=0) →
   its archived `deprecated_normal` is the only trace; noted in report.

## Verification (post-migration, in the tool + separate script)

- Per-table row-count parity (source vs. target).
- `member_exp.lifetime == SUM(member_exp_log.exp)` per uid (target guild) —
  exact match required; guaranteed by the sentinel.
- `member_frog.capture` vs. `member_frog_log` counts per uid — expected
  divergence allowed (capture is a lifetime counter, logs may have been
  pruned); reported, not failed.
- Poll vote totals; `rank_threshold` ordering; settings key presence.
- Bot's own derivation paths run on a **copy** of the migrated DB:
  `sync_with_exp_logs`, `sync_with_frog_logs`, seasonal/lifetime level calc —
  zero drift expected.

## Rollback

The existing `data/cazzubot.db` is backed up to
`data/cazzubot.db.bak-<timestamp>` before the swap; restore to roll back.
The migration never touches the source PostgreSQL.
