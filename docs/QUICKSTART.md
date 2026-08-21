# Quick start

Get from a fresh clone to running code in a few minutes. Skim it, then dig
into the [How do I...](../README.md) pages when you hit a specific task.

## 1. Install

```sh
uv sync
cp .env.example .env
```

Edit `.env` and fill in at least:

- `TOKEN_DEV` — your development bot token.
- `OWNER_ID` — your user id.
- `GUILD_ID_DEV` — your development guild id.

Production values (`TOKEN`, `GUILD_ID_PROD`) are only needed if you run the
production bot. You almost never do.

## 2. Run

```sh
uv run python main.py -d            # development bot + guild (the default)
uv run python main.py -d -s         # sandbox: only poll + dev plugins
uv run python main.py -d -s frogs   # sandbox: frogs + its dependencies
```

`-d` means development bot + development guild. The bot serves **one guild**
and keeps development and production data in separate sqlite files, so a dev
run can't touch production.

The sandbox (`-s`) loads only the plugins you name plus their dependencies.
Use it to test a single feature in isolation.

## 3. The edit → reload loop

While developing a plugin:

1. Edit the code.
2. If you only changed an extension (commands, listeners), hot-reload it
   from Discord: `/plugin reload <name>`.
3. Otherwise restart the bot (`Ctrl+C`, then run again).

Schema changes (new tables/columns) need a restart. See
[create a new plugin](create-a-plugin.md) for the file layout.

## 4. Checks

Run these before finishing a change:

```sh
uv run ruff check .            # lint
uv run ruff format .           # format
uv run basedpyright            # types
uv run pytest                  # offline unit + integration tests
```

Tests run entirely offline (no Discord connection). For interactive flows
(buttons, modals, slash commands) use the test driver described in
`tests/driver.py` and `needs-rewrite/TESTING.md`.

## 5. Where things live

- `main.py` — entry point.
- `cazzubot/` — core package: bot, config, db, items, assets, scheduler.
- `plugins/` — one folder per feature; the bot auto-discovers them.
- `tests/` — offline tests; `tests/fakes.py` has typed hikari fakes.
- `data/` — per-guild sqlite files (created on first boot, gitignored).

## Next steps

- Want to add something? Pick a **How do I...** page from the
  [index](../README.md).
- Want the full picture? Read `AGENTS.md` and the old docs under
  `docs/needs-rewrite/`.
