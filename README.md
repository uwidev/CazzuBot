# CazzuBot

Discord bot for [Club Cirno](https://discord.gg/club-cirno): experience/levels,
ranked roles, frog-token economy, leaderboards, seasonal resets, moderation,
polls, welcomes and assorted server utilities.

This is the **v2 rewrite** on the `rewrite` branch: plugin-based, SQLite
(no PostgreSQL/docker), single guild, discord.py 2.7.1. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

## Setup

```sh
uv sync
cp .env.example .env   # fill in TOKEN_DEV / OWNER_ID / GUILD_ID
uv run python main.py -d          # dev (prefix d!, debug gating on)
uv run python main.py -p          # production (prefix c!)
uv run python main.py -d -s       # sandbox: only poll, board, dev plugins
```

The database is a single sqlite file (`data/cazzubot.db`) created on first
boot. No docker, no Postgres.

## Adding a feature (the whole point)

Drop a folder into `plugins/` with a `plugin = MyPlugin()` instance — the bot
auto-discovers it, applies its schema, registers its cogs and scheduled-task
handlers. See [docs/PLUGINS.md](docs/PLUGINS.md).

## Commands

- Run: `uv run python main.py [-d|-p|-s]`
- Lint: `uv run ruff check .` — Format: `uv run ruff format .`
- Boot check: `uv run python scripts/smoke.py`
- Data-layer checks: `uv run python scripts/functest.py`
- No unit-test suite (yet).

## Features

- **experience** — message exp (cooldown + diminishing returns), Club
  Membership Card, seasonal/lifetime leaderboards with paging, quiet channels
- **levels** — configurable level-up message (JSON templates)
- **ranks** — level thresholds → roles, seasonal + lifetime windows,
  rank-up messages, keep_old role integrity
- **frogs** — timed frog spawns (interval ± fuzzy%), capture race, frog
  inventory (normal/frozen), consume frogs for exp, quarterly freeze
- **daily / quarterly** — reset message counts/cooldowns; freeze frogs per
  quarter (missed resets run on boot)
- **mod** — warn/mute/kick/ban with modlog + scheduled mute/tempban expiry
- **poll** — app-command polls with a vote modal
- **welcome** — onboarding/role-based welcomes with JSON message templates
- **counter** — the baka button
- **board** — weekly image scrape
- **fun** — ping/info/noot, echo, inktober, story compiler
- **dev** — owner tools, plugin hotswap (`cog reload <name>`)
