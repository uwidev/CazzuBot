# CazzuBot

Discord bot for Club Cirno — v2 rewrite: plugin-based, SQLite, single guild. Python 3.14 + discord.py 2.7.1 + aiosqlite, managed with uv. Runs as `main.py`.

## Project

- Entry point: `main.py` (`-d` debug, `-p` production, `-s` sandbox = only poll/board/dev plugins; prefix `d!` / `c!`). Reads `TOKEN`/`TOKEN_DEV`, `OWNER_ID`, `GUILD_ID`, `DB_PATH` from `.env` (see `.env.example`).
- `cazzubot/` = core package (bot, db, settings, scheduler, plugin loader, utils, levels, leaderboard, templates, timeparse); `plugins/` = one folder per feature, auto-discovered; `board/`/`download/`/`emojis/` = asset dirs (gitignored).
- Single sqlite file `data/cazzubot.db`, created on first boot — no docker/Postgres. v1 data is not migrated.
- Design docs: `docs/ARCHITECTURE.md`, `docs/PLUGINS.md`. **Read PLUGINS.md before adding a feature.**

## Commands

- Install: `uv sync`
- Run: `uv run python main.py -d` (dev) / `-p` (prod) / `-s` (sandbox)
- Lint: `uv run ruff check .` — Format: `uv run ruff format .`
- Boot check: `uv run python scripts/smoke.py` — data-layer checks: `uv run python scripts/functest.py`
- No unit-test suite.

## Architecture

- `cazzubot/bot.py` — `CazzuBot(commands.Bot)`: owns `config`, `db`, `settings`, `scheduler`, `plugins`; two-phase plugin load (schemas+cogs first, then `on_load` hooks — no load-order deps); debug gating.
- `cazzubot/db.py` — `Database`: aiosqlite wrapper (WAL, FK on, explicit `transaction()`), `execute/fetchall/fetchone/fetchval/executemany`, `dump_json/load_json`. Enums → TEXT, timestamps → ISO-8601 UTC.
- `cazzubot/plugin.py` — `Plugin` base (`name`, `cogs`, `schema`, `scheduled`, `on_load`/`on_unload`) + `discover_plugins()` (packages or single modules; each defines `plugin = MyPlugin()`).
- `cazzubot/scheduler.py` — one loop over `tasks(tag, run_at, payload)`; tags registered via `Plugin.scheduled`; handlers re-schedule by inserting rows. Replaces frog/counter/mod expiry loops.
- `cazzubot/settings.py` — JSON key-value store (single guild), namespaced keys (e.g. `frog.enabled`, `rank.seasonal.message`, `level.quiet`).
- `cazzubot/window.py` — buffered, level-tagged command reporting to Discord (`command_window(ctx)` CM, `@windowed` decorator, `window_*` one-off helpers); auto-flushes at end of command and on error; ephemeral on slash. Distinct from CLI logging.
- Plugins: experience (message exp pipeline + membership card + `exp top` paging), levels, ranks (thresholds → roles, seasonal/lifetime), frogs (spawn cadence `interval ± fuzzy%`, capture, consume-for-exp, quarterly freeze), daily, quarterly, mod (modlog + scheduled mute/tempban), poll (app commands + modal view), welcome, counter (baka button), board, fun (member/echo/inktober/story), dev (owner tools + `cog reload` hotswap).
- Cross-plugin flow: `experience.on_message` awards exp then calls `plugins.levels.cog.handle_level_up` and `plugins.ranks.logic.handle_ranks`.

## Conventions

- **Spaces**, double quotes, line-length 75 (`ruff format`). Run `ruff check` after edits.
- Plugins reach services via `bot.db`, `bot.settings`, `bot.scheduler`, `bot.config`, `bot.guild`. Plugin db modules take `db: Database` (or `settings: Settings`) as first arg; cogs take the bot.
- No `gid` columns anywhere; no FK decorators; `INSERT OR IGNORE`/`INSERT OR REPLACE` for idempotent writes.
- `tasks.loop(time=…)` only for daily/quarterly cadence (with missed-run force check on boot); everything delayed goes through the scheduler.
- User-configurable message JSON goes through `cazzubot.templates.verify/prepare` (jsonschema-validated); placeholders applied via `utils.deep_map` + per-feature formatters.
- Time handled with pendulum, always UTC (see `cazzubot/timeparse.py`).
- Command feedback goes through `cazzubot.window` (levels debug/info/success/warn/error; success/warn/error prefix ✓/⚠︎/✖) — no emoji-reaction feedback. CLI `logging` stays for bot internals (db, connection, plugin hooks); command-local state goes to the user via the window, flushed before blocking ops and always at command end (even on error).
- Ruff select `["E4", "E7", "E9", "F"]`; basedpyright config present (Python 3.14, Linux).

## Notes

- `frog register`/`exp`/`rank`/`level`/`welcome`/`frog set` require admin; `consume` confirms via a Yes/No button view (`cazzubot.utils.ConfirmView`).
- Deploy: `push_to_prod.sh` (untracked, machine-specific).
