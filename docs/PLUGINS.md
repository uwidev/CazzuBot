# How to add a feature plugin

This is the core workflow of the v2 architecture. A feature is **one folder**;
everything it needs lives inside it. No central registration anywhere.

## The contract

Create `plugins/myfeature/__init__.py`:

```python
from discord.ext import commands
from cazzubot import Plugin


class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def hello(self, ctx):
        await ctx.send("world")


class MyFeature(Plugin):
    name = "myfeature"  # unique id (defaults to folder name)
    cogs = [MyCog]  # cog classes (any number)
    schema = [  # DDL, idempotent, runs at boot
        "CREATE TABLE IF NOT EXISTS myfeature (key TEXT PRIMARY KEY, value TEXT)",
    ]
    scheduled = {
        "mytag": my_due_handler
    }  # tag -> async handler(bot, payload)

    async def on_load(self, bot):
        """Optional startup hook (after every plugin's schema/cogs are ready)."""

    async def on_unload(self, bot):
        """Optional teardown hook."""


plugin = MyFeature()
```

Restart (or `c!cog reload myfeature` if dev is loaded) — done.

For very small features, a single module `plugins/myfeature.py` with the same
`plugin = MyFeature()` line works too.

## Services available on the bot

Every cog gets the bot injected; use these instead of reaching into internals:

- `bot.db` — sqlite queries:
  `await bot.db.fetchall("SELECT * FROM t WHERE x = ?", x)`,
  `await bot.db.execute(...)`, `bot.db.transaction()` for multi-statement writes
- `bot.settings` — JSON key-value store, namespace your keys:
  `await bot.settings.get("myfeature.flag", False)`, `await bot.settings.set(...)`
- `bot.scheduler` — delayed tasks that survive restarts:
  `await bot.scheduler.add("mytag", when, {"payload": 1})`; register the tag in
  `scheduled`. The handler re-schedules by adding a new row.
- `bot.config` — `token`, `owner_id`, `guild_id`, `debug`, `sandbox`, `prefix`
- `bot.guild` — the one guild this bot serves

## Conventions

- One plugin = one feature. Split big features into `db.py` (queries/schema),
  `cog.py` (commands), `logic.py` (pure logic) inside the plugin folder.
- **CSR boundary:** service (`logic.py`/`factory.py`) and repository (`db.py`)
  modules take `db`/`settings` + plain values (+ injected `now`) and must
  **not** `import discord` — discord objects cross only the controller
  boundary (pure-data `discord.Embed`/`Permissions`/`Colour` are fine). A new
  plugin may start monolithic, but settles into this split via
  test-then-extract. Enforced by `tests/core/test_csr_boundary.py`; the
  allowlisted exceptions are the tracked remainder of the CSR backlog item.
- Enums are stored as TEXT; timestamps as ISO-8601 UTC strings; dicts/lists as
  JSON text (see `bot.db.dump_json` / `load_json`).
- No `gid` columns — this bot serves one guild. Check `bot.config.guild_id`
  where it matters.
- Prefix settings with the plugin name to avoid collisions in `settings`.
- Message templates (level-up, rank-up, frog, welcome) go through
  `cazzubot.templates.verify` / `prepare` so they stay jsonschema-validated.
- Format with `ruff format` (tabs, line-length 75) and run `ruff check`.
