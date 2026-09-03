# CazzuBot

Discord bot for [Club Cirno](https://discord.gg/club-cirno): experience and
levels, ranked roles, a frog-token economy, leaderboards, moderation, polls,
welcomes, and assorted server utilities.

This is the **v2 rewrite**: plugin-based, SQLite, single guild. Python 3.14 +
hikari 2.5 + hikari-lightbulb 3.2, managed with [uv](https://docs.astral.sh/uv/).

## Quick start

New to the codebase, or coming back? Start with the
[quick start guide](docs/QUICKSTART.md) — install, run, lint, test, and the
edit-reload loop.

## How do I...

Jump straight to the task you're doing. Each page is a short, concrete walkthrough.
See the [quick start index](docs/QUICKSTART.md) for the task list.

## Reference

The older in-depth docs still describe the design and internals. They live
under [docs/needs-rewrite](docs/needs-rewrite/) while they're being reworked;
expect them to be cleaned up and re-indexed here as they land.

| Doc                                                               | What it covers                                 |
| ----------------------------------------------------------------- | ---------------------------------------------- |
| `docs/needs-rewrite/ARCHITECTURE.md`                              | overall design, core services, plugin loader   |
| `docs/needs-rewrite/PLUGINS.md`                                   | plugin structure, conventions, dependencies    |
| `docs/needs-rewrite/PLUGIN_ARCHITECTURE.md`                       | plugin lifecycle, scheduling, event bus        |
| `docs/SYSTEMS.md`                                                 | one-page systems map (core, manifest, plugins) |
| `docs/GLOSSARY.md`                                                | stabilized vocabulary (status, outcome, seam)  |
| `docs/needs-rewrite/TESTING.md`                                   | layered test approach, live-verification gaps  |
| `docs/needs-rewrite/ASSETS.md`                                    | asset pipeline design record                   |
| `docs/needs-rewrite/MIGRATION.md`                                 | v1 → v2 data migration                         |
| `docs/needs-rewrite/MANUAL_TEST.md`                               | manual verification checklist                  |
| `docs/needs-rewrite/ROADMAP.md`                                   | implementation phases                          |
| `docs/needs-rewrite/BACKLOG.md` / `docs/needs-rewrite/DONE.md`    | planned vs. shipped ideas                      |
| `docs/needs-rewrite/ITEMS.md` / `docs/needs-rewrite/INVENTORY.md` | item/inventory design                          |
| `docs/needs-rewrite/FROG.md`                                      | frog system notes                              |
| `docs/needs-rewrite/HANDOFF_ITEMS.md`                             | handoff notes on item work                     |

## Repository layout

```
main.py                     entry point
cazzubot/                   core package (bot, config, db, items, assets, …)
plugins/                    one folder per feature, auto-discovered
tests/                      offline unit + integration tests
scripts/                    migration and tooling scripts
docs/                       this index, quick start, how-tos, old docs
```

## Conventions (the short version)

Read `AGENTS.md` for the full set; the ones you'll hit constantly:

- Spaces, double quotes, 75-char lines — `ruff format` handles it.
- Common noun first for paired variables: `SCRAPE_CHANNEL_DEV` / `SCRAPE_CHANNEL_PROD`.
- Scripts are top-down: docstring → imports → constants → core functions → helpers → `if __name__ == "__main__":`.
- Slash commands are guild-scoped; new guild listeners use `guild_listener`.
- The bot serves ONE guild. Development and production data never mix.
