# CazzuBot v2 — Architecture

A ground-up rewrite of the bot on the `rewrite` branch. Goals, in the user's words:

1. **Trivially add new features** — zero friction, no touching shared files.
2. **SQLite instead of PostgreSQL** — one file, no docker, no asyncpg, no codecs.
3. **Latest discord.py (2.7.1)**.
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
    bot.py                  CazzuBot(commands.Bot) — owns db, settings, scheduler, plugins
    config.py               Config dataclass from env; ONE guild_id
    db.py                   Database — aiosqlite wrapper, WAL, FK on, explicit transactions
    settings.py             settings(key, value) JSON key-value store (single guild)
    window.py               buffered, level-tagged command reporting to Discord (CM + @windowed + one-off helpers)
    plugin.py               Plugin base + auto-discovery of plugins/
    scheduler.py            one central task loop over the tasks table
    utils.py                OldNew, ordinal, percentile, embeds, confirm, month2season…
    timeparse.py            port of src/ntlp.py (natural-language time parsing)
    templates.py            port of src/user_json.py (JSON message templates + jsonschema)
    leaderboard.py          port of src/leaderboard.py (rendering)
    levels.py               port of src/levels_helper.py (exp/level math)
    models.py               shared enums (WindowEnum, FrogTypeEnum, …)
plugins/                    one self-contained package per feature
    <feature>/__init__.py   defines `plugin = MyFeature()`
```

## The plugin contract (this is the whole point)

A feature is **one folder**. To add a feature, drop this in `plugins/myfeature/__init__.py`
and restart — the loader finds it, runs its schema, registers its cogs, done:

```python
from discord.ext import commands
from cazzubot import Plugin


class MyFeature(Plugin):
    name = "myfeature"
    cogs = [MyCog]  # any number of cog classes
    schema = ["CREATE TABLE IF NOT EXISTS myfeature (…)"]
    scheduled = {"mytag": my_handler}  # tag -> async handler(bot, payload)

    async def on_load(self, bot): ...  # optional startup hook
    async def on_unload(self, bot): ...  # optional teardown hook


plugin = MyFeature()
```

No central registration, no `db.init()`, no codec setup, no imports to add anywhere. Plugins
reach shared services through the bot: `bot.db`, `bot.settings`, `bot.scheduler`,
`bot.config`. Their cogs get `bot` injected at load.

## Data layer

- SQLite at `data/cazzubot.db` (configurable), `PRAGMA journal_mode=WAL`,
  `PRAGMA foreign_keys=ON`, busy timeout; one aiosqlite connection (all operations
  serialized), explicit `BEGIN IMMEDIATE`/`COMMIT` transactions guarded by an asyncio lock.
- Enums stored as TEXT; timestamps as ISO-8601 strings; dicts/lists as JSON text.
- Generic `settings(key, value)` store replaces `db/guild.py`, `db/internal.py`, and most
  per-feature settings getters. Feature tables only for relational data
  (rank_thresholds, frog_spawns, polls, modlog, member stats, exp/frog logs, counters, tasks).
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
handler; the handler re-schedules by inserting a new row. Replaces the frog / counter /
mod expiry loops. Daily & quarterly resets keep their own `tasks.loop(time=…)` plus a
force-reset-on-boot check (as v1 did).

## Single guild

`Config.guild_id` is the one server. Cogs that need a guild resolve it from the bot and
short-circuit elsewhere. Commands that are meaningless outside the server can be ignored.

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
