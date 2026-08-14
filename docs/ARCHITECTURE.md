# CazzuBot v2 — Architecture

A ground-up rewrite of the bot on the `rewrite` branch. Goals, in the user's words:

1. **Trivially add new features** — zero friction, no touching shared files.
2. **SQLite instead of PostgreSQL** — one file, no docker, no asyncpg, no codecs.
3. **hikari 2.5 + hikari-lightbulb 3.2** (was discord.py 2.7.1).
4. **Single server** — one guild, no `gid` plumbing anywhere.

## What was wrong with v1 (the friction)

- **Three-layer sprawl**: a feature was spread across `ext/<name>.py` (cog), `src/<name>.py`
  (domain), `src/db/<name>.py` (queries), `src/db/table.py` (dataclasses) — plus enum codec
  registration in `main.py` and `db.init()` dependency-injection hooks to break circular imports.
- **FK auto-insert decorators** (`@fkey_gid`, `@fkey_member`, …) — you can't read a query
  function without understanding the decorator stack.
- **Per-guild everywhere**: every table carried `gid`, every query filtered by it, and a whole
  `db/guild.py` of per-guild settings getters/setters.
- **Four polling loops** on the same `task` table (frog spawn, counter expiry, mod expiry, plus
  daily/quarterly loops) — scheduling logic duplicated per cog.
- **`SnowflakeTable.__iter__` / `values()`** string-format SQL generation, JSONB subset matching,
  asyncpg enum codecs.

## New layout

```
main.py                     thin entrypoint (flags -d/-p/-s)
cazzubot/                   the core package (replaces src/)
    bot.py                  CazzuBot(hikari.GatewayBot) + lightbulb client — owns db, settings,
                            scheduler, plugins, assets, events, inventory, member_effects, lifecycle
    config.py               Config dataclass from env; ONE guild_id
    db.py                   Database — aiosqlite wrapper, WAL, FK on, explicit transactions
    settings.py             settings(key, value) JSON key-value store (single guild)
    window.py               buffered, level-tagged command reporting to Discord (CM + @windowed + one-off helpers)
    plugin.py               Plugin base + auto-discovery of plugins/ (two-phase load, verify_schema boot guard)
    scheduler.py            one central task loop over the tasks table
    assets.py               Assets — enum-declared files (reconcile + CDN sync)
    events.py               Events — typed EventBus (on/off, unsubscribe tokens)
    inventory.py            Inventory — generic (uid, item, qty) ledger
    member_effects.py       MemberEffects — (uid, key, value, expires_at) with lazy expiry
    lifecycle.py            Lifecycle — plugin defer/withdraw undo stacks (reversible reload)
    utils.py                OldNew, ordinal, percentile, embeds, confirm, month2season…
    timeparse.py            port of src/ntlp.py (natural-language time parsing)
    templates.py            port of src/user_json.py (JSON message templates + jsonschema)
    leaderboard.py          port of src/leaderboard.py (rendering)
    levels.py               port of src/levels_helper.py (exp/level math)
    models.py               shared typed keys (SpeciesKey, FrogState, EffectKey, …)
plugins/                    one self-contained package per feature
    <feature>/__init__.py   defines `plugin = MyFeature()`
```

## The plugin contract (this is the whole point)

A feature is **one folder**. To add a feature, drop this in `plugins/myfeature/__init__.py`
and restart — the loader finds it, runs its schema, registers its cogs, done:

```python
from cazzubot import Plugin


class MyFeature(Plugin):
    name = "myfeature"
    extensions = ["plugins.myfeature.cog"]  # lightbulb loader modules
    schema = ["CREATE TABLE IF NOT EXISTS myfeature (…)"]
    scheduled = {"mytag": my_handler}  # tag -> async handler(bot, payload)
    asset_decl = {MyAsset: "path"}     # optional enum -> file declarations
    depends_on = ()                    # optional plugin names, load-ordered

    async def on_load(self, bot): ...  # optional startup hook
    async def on_unload(self, bot): ...  # optional teardown hook


plugin = MyFeature()
```

No central registration, no `db.init()`, no codec setup, no imports to add anywhere. Plugins
reach shared services through the bot: `bot.db`, `bot.settings`, `bot.scheduler`,
`bot.assets`, `bot.events`, `bot.inventory`, `bot.member_effects`, `bot.lifecycle`,
`bot.config`. Their cogs get `bot` injected at load. Loading is two-phase (schemas +
extensions first, then `on_load`), so plugins have no load-order dependencies;
`verify_schema` aborts boot if the DB schema drifts from the Python DDL.

## Shared services

The generic game stores and glue live on `bot` so features don't re-implement them:

- **`bot.inventory`** — a `(uid, item, qty)` ledger (keyed on typed enum keys). Frogs
  use it directly; nothing is frog-specific inside.
- **`bot.member_effects`** — per-member scalar effects with expiry (e.g.
  `MemberEffectKey.EXP_MULTIPLIER`, consumed by the experience pipeline). Expiry is lazy
  (expired rows are ignored/pruned on read).
- **`bot.events`** — a typed event bus (`on` returns an unsubscribe token, `off` removes
  handlers). Emitters/subscribers are named in code comments so the call graph stays
  obvious.
- **`bot.lifecycle`** — plugins defer reversible operations (undo callables); `withdraw`
  replays them in reverse with failure isolation, so unloading/reloading a plugin is
  safe. `cog reload` unloads dependents first (reverse-topological, SCC-aware).
- **`bot.assets`** — enum-declared files (`asset_decl`) reconciled to disk and synced to
  the CDN channel. See `docs/ASSETS.md`.

The full lifecycle contract (defer/withdraw ordering, state-backed scheduling,
unload/on_load semantics) is in `docs/PLUGIN_ARCHITECTURE.md`; the system map is
`docs/SYSTEMS.md`.

## Data layer

- Per-guild SQLite files `data/cazzubot-prod.db` / `data/cazzubot-dev.db`
  (configurable via `DB_PATH_PROD`/`DB_PATH_DEV`), `PRAGMA journal_mode=WAL`,
  `PRAGMA foreign_keys=ON`, busy timeout; one aiosqlite connection (all operations
  serialized), explicit `BEGIN IMMEDIATE`/`COMMIT` transactions guarded by an asyncio lock.
- Enums stored as TEXT; timestamps as ISO-8601 strings; dicts/lists as JSON text.
  Typed keys (`SpeciesKey`, `FrogState`, `EffectKey`, `InventoryKey`, …) are the
  canonical spelling everywhere — no magic strings in code or SQL.
- Generic `settings(key, value)` store replaces `db/guild.py`, `db/internal.py`, and most
  per-feature settings getters. Feature tables only for relational data
  (rank_thresholds, frog_spawns, polls, modlog, member stats, exp/frog logs, counters, tasks).
- Generic ledgers live in core, not per-feature tables: `bot.inventory`
  (`(uid, item, qty)`) and `bot.member_effects` (`(uid, key, value, expires_at)`) — no
  `frog_inventory`-style tables.
- No `gid` columns anywhere. `users`/`members` tables kept minimal (`INSERT OR IGNORE`
  on demand — no decorator magic).

## Command feedback

Commands signal their result through `cazzubot/window.py` — a buffered,
level-tagged window into the command's internal state, sent to the invoker
(ephemeral on slash). Levels `success`/`warn`/`error` prefix unicode text
symbols (`✓`/`⚠︎`/`✖`); `debug`/`info` are plain. Lines buffer and flush as
**one** message: explicitly before blocking work (big disk/DB ops), and always
at the end of the command — including on error. No emoji-reaction feedback.

Three forms: `async with command_window(ctx) as window:` (CM), `@windowed`
(exposes `ctx.window`, auto-flush), and one-off `window_*` helpers. A command
whose own output is the signal (leaderboards, embeds, the spawned frog) needs
no window at all. CLI `logging` stays for bot internals (db, connection,
plugin hooks) — command-local state goes to the user, not the CLI log.

## Scheduling

One `Scheduler` (a single `tasks.loop(seconds=1)`) polls `tasks(tag, run_at, payload)`.
Plugins register handlers per tag (see `scheduled` above). Due tasks dispatch to their
handler; the handler re-schedules by inserting a new row. Cadences are **owned by the
plugin that owns the data** — there are no wrapper plugins:

- `daily` → experience (midnight exp reset)
- `daily.frog` + `quarterly` → frogs (midnight capture resync; Jan/Apr/Jul/Oct freeze)

Every scheduled handler re-arms itself on due and on `on_load` (missed runs force-fire
on boot). Unload withdraws the plugin's scheduler rows — **tasks are projections; state
is the source of truth** (see `docs/PLUGIN_ARCHITECTURE.md`).

## Single guild

`Config.guild_id` is the one server. Extensions that need a guild resolve it
from the bot (`bot.guild` from the cache) and short-circuit elsewhere.
Commands are slash-only and guild-scoped via the lightbulb client's
`default_enabled_guilds`.

## Kept from v1 (faithful ports)

Exp formula & message-exp cooldown curve, seasonal (0–3) windows & quarterly freeze,
frog cadence `interval ± fuzzy%` + capture flow, frog→exp conversion (10/3),
rank thresholds with enabled/keep_old, JSON message templates (`templates.py`,
jsonschema-validated, `{placeholder}` formatters), ntlp time parsing, leaderboard
rendering format, poll modal/vote flow, welcome PENDING/ROLE modes, modlog
warn/mute/kick/ban + expiry, baka counter, board scrape, quiet channels, resync
commands, `exp top` paging.

## Dropped / simplified

Per-guild plumbing, FK decorators, asyncpg codecs, `SnowflakeTable` SQL-string hacks,
JSONB subset matching, `db.init()` DI, partitioned-log scaffolding, multi-guild
"good practices" that were never used.

## Migration

v1 PostgreSQL data is migrated with the one-off scripts in `scripts/`
(`migrate_pg_to_sqlite.py`, `verify_migration.py`, `boot_check_migrated.py`).
The ops protocol is documented in `docs/MIGRATION.md`; the per-table transform
spec in `scripts/migration/MAPPING.md`. The source PostgreSQL is never
written to; the migration is re-runnable and verified per-uid before the
SQLite file is swapped in.
