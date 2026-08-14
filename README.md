# CazzuBot

Discord bot for [Club Cirno](https://discord.gg/club-cirno): experience/levels,
ranked roles, frog-token economy, leaderboards, seasonal resets, moderation,
polls, welcomes and assorted server utilities.

This is the **v2 rewrite**: plugin-based, SQLite (no PostgreSQL/docker),
single guild, Python 3.14 + hikari 2.5 + hikari-lightbulb 3.2, managed with uv.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

## Setup

```sh
uv sync
cp .env.example .env   # fill in TOKEN_DEV / OWNER_ID / GUILD_ID_PROD / GUILD_ID_DEV
uv run python main.py -d            # develop bot + guild (default)
uv run python main.py -b production -g production  # production bot + guild
uv run python main.py -d -s         # sandbox: only poll, dev plugins
uv run python main.py -d -s frogs   # sandbox: frogs + its dependencies
                                    # (experience, levels, ranks)
```

Databases are per-guild sqlite files (`data/cazzubot-prod.db` /
`data/cazzubot-dev.db`) created on first boot, so dev and prod data never mix.
No docker, no Postgres.

## Adding a feature (the whole point)

Drop a folder into `plugins/` with a `plugin = MyPlugin()` instance — the bot
auto-discovers it, applies its schema, registers its cogs and scheduled-task
handlers. See [docs/PLUGINS.md](docs/PLUGINS.md); read
[docs/PLUGIN_ARCHITECTURE.md](docs/PLUGIN_ARCHITECTURE.md) and
[docs/SYSTEMS.md](docs/SYSTEMS.md) for how the pieces fit together.

## Commands

- Run: `uv run python main.py [-d|-p|-s [PLUGIN ...]]`
- Lint: `uv run ruff check .` — Format: `uv run ruff format .` — Types:
  `uv run basedpyright`
- Tests: `uv run pytest` — offline unit/integration tests; no Discord
  connection, typed fakes in `tests/fakes.py`. See `docs/TESTING.md`.

## Features

- **experience** — message exp (cooldown + diminishing returns), Club
  Membership Card, seasonal/lifetime leaderboards with paging, quiet
  channels; owns the midnight exp reset
- **levels** — configurable level-up message (JSON templates)
- **ranks** — level thresholds → roles, seasonal + lifetime windows,
  rank-up messages, keep_old role integrity
- **frogs** — timed frog spawns (interval ± fuzzy%), capture race, frog
  inventory (normal/frozen), consume frogs for exp, species/effects via
  typed keys; owns the quarterly freeze and midnight capture resync
- **mod** — warn/mute/kick/ban with modlog + scheduled mute/tempban expiry
- **poll** — app-command polls with a vote modal
- **welcome** — onboarding/role-based welcomes with JSON message templates
- **counter** — the baka button
- **board** — weekly image scrape → numbered grid posting (core;
  weekly automation + poll tie-in backlogged in `docs/BACKLOG.md`)
- **misc** — server utilities: guild banner, welcome screen
  (API-editable parts)
- **fun** — ping/info/noot, echo, inktober, story compiler
- **dev** — owner tools, plugin hotswap (`cog reload <name>`)

Shared services on `bot` (inventory, member effects, typed event bus,
plugin lifecycle, assets) are covered in `docs/PLUGINS.md` and
`docs/PLUGIN_ARCHITECTURE.md`.

## Docs index

| Doc | What it's for |
| --- | --- |
| `docs/ARCHITECTURE.md` | overall design, core services, plugin loader |
| `docs/PLUGINS.md` | adding a plugin: structure, conventions, dependencies |
| `docs/PLUGIN_ARCHITECTURE.md` | plugin lifecycle contract, state-backed scheduling, event bus |
| `docs/SYSTEMS.md` | system map (mermaid) of plugins and shared services |
| `docs/TESTING.md` | layered test approach, what needs live verification |
| `docs/MIGRATION.md` | v1 → v2 data migration |
| `docs/ROADMAP.md` | implementation phases (0–3 done) |
| `docs/BACKLOG.md` / `docs/DONE.md` | planned vs. shipped ideas |
| `docs/ASSETS.md` | asset pipeline (species art, CDN sync) |
| `docs/MANUAL_TEST.md` | manual verification checklist |
