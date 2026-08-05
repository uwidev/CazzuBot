# CazzuBot

Discord bot for Club Cirno: experience/leveling, ranked roles, frog-token spawning, leaderboards, seasonal resets, mod/poll/welcome utilities. Python 3.10 + discord.py 2.3.2 + asyncpg (Postgres 16), managed with uv, dockerized.

## Project

- Entry point: `main.py` (argparse: `-d` debug, `-p` production, `-s` sandbox; prefix `d!` / `c!`). Reads tokens/DB creds from `.env` (env vars `SECRET`, `TOKEN`, `TOKEN_DEV`, `POSTGRES_*`), opens the asyncpg pool, registers enum/json codecs (`setup_codecs`), then loads extensions.
- `src/` = non-cog shared logic; `ext/` = one discord.py cog per file; `board/` = image assets (not source); `docs/Tasks.md` = task-loop conventions.
- No tests exist. Secrets live in `.env` / `secret/` — never log or commit them.

## Commands

- Install: `uv sync` (or `pip install -r requirements.txt`)
- Run (needs Postgres running + `.env`): `uv run python main.py -d` (dev) / `-p` (prod) / `-s` (sandbox only loads `ext.poll`, `board`, `dev`, `hotswap`)
- Database: `docker compose up -d database` (Postgres 16 on :5432)
- Full container: `docker compose up --build`
- Lint: `uv run ruff check .` — format: `uv run ruff format .` — or `uv run pre-commit run --all-files` (black + ruff)
- There is no test command.

## Architecture

- `src/cazzubot.py` — `CazzuBot(commands.Bot)` subclass: holds `pool`, `ext_path`; auto-loads all `ext/*.py` except `sandbox.py`; `is_dev_mode` gate in debug.
- `src/db/` — one module per table (level, rank, frog, member_exp, modlog, poll, welcome, …), thin `asyncpg` query wrappers taking `pool` first. `table.py` defines `SnowflakeTable` dataclasses (`from_record()`, `__iter__` for `*level` unpacking) and the enums (`WindowEnum`, `FrogTypeEnum`, `ModlogStatusEnum`, …).
- `src/*.py` — domain logic: `level.py`/`rank.py` (public-facing per-feature API), `leaderboard.py` (table rendering), `frog_factory.py` (spawn tasks), `ntlp.py` (natural-language time parsing, UTC-internal), `user_json.py` (validates user-defined JSON messages via jsonschema + `utility.deep_map` formatters), `utility.py` (helpers).
- `ext/` — cogs: experience (exp math, cooldowns), frog (token economy), rank, mod, poll, welcome, board, counter, daily/quarterly (reset tasks), dev, owner, hotswap, echo, inktober, story, member. `sandbox.py` is special-cased.

## Conventions

- **Tabs** for indentation (ruff `indent-style = "tab"`), double quotes, line length 75. Run `ruff format` after edits — the codebase was `retab!` to tabs.
- Module-private constants prefixed `_` (e.g. `_BASE`, `_BONUS` in `ext/experience.py`); module logger `_log = logging.getLogger(__name__)`.
- Cogs: `class X(commands.Cog)` + `async def setup(bot)`; import `CazzuBot` from `main` under `if TYPE_CHECKING:`; annotate `ctx: commands.Context`.
- DB: build queries in `src/db/*.py`, expose dataclasses from `src.db.table`, cast `Record` → table object via `from_record`; guard writes with existence checks (`if not await guild.get(pool, gid)`). New enums stored in Postgres must be registered as codecs in `main.py:setup_codecs`.
- Success feedback via emoji reaction (`await ctx.message.add_reaction("👍")`); time handled with `pendulum`, always stored/computed in UTC (see `src/ntlp.py`).
- Ruff select is `["E4", "E7", "E9", "F"]` (pyproject.toml); `basedpyright` config also present (Python 3.10, Linux).

## Notes

- (add later)
