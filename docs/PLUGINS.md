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

## Roles plugin — declarative role manifest

`plugins/roles/` hosts the **boot-time drift check only**. All enforcement is
manual via the CLI; the plugin never applies anything.

The manifest (`roles.manifest` at the repo root, committed) is the source of
truth for role structure. **Order is positional**: an export writes every
role in its exact Discord sidebar order, and `diff`/`apply` enforce that
order. **Groups are marker roles**: a Discord role named `[Group]` marks
the start of a group — everything below it until the next marker belongs to
it. The manifest header `[Group]` maps to that marker role (created by the
engine if missing). Roles can also appear header-less (implicit group).
Line format:

```
[Group]                 group-marker role (named "[Group]" on discord);
                        everything below it until the next marker belongs
                        to this group
Role Name               verbatim Discord name
Role Name : token …     tokens: hoist | mentionable | #rrggbb |
                        preset:<name> | +flag | -flag | icon:<emoji>
[preset name]           permission preset section; flag lines below it
# comment               blank lines and # comments are ignored
```

- Final perms = preset ∪ `+flags` − `-flags`; a role with no tokens gets
  empty permissions. Names are verbatim (identity); `@everyone` is reserved.
- Renames: write `Old Name->New Name : tokens` on the role line — the live
  role is renamed (memberships survive) and the manifest line is rewritten
  to just `New Name : tokens` after a successful apply. A rename whose new
  name already exists is a conflict and blocks apply. `diff` also suggests
  read-only "did you mean rename?" hints for close delete+create pairs.
- Engine (pure, offline-tested): `cazzubot.roles.parser` (parse),
  `cazzubot.roles.export` (snapshot → manifest), `cazzubot.roles.plan`
  (diff → Plan). Executor (live): `cazzubot.roles.executor`.
- Admin CLI — single entry, one domain per feature:
  `uv run cazzubot-cli <domain> <verb>` (or `uv run python -m
  cazzubot.cli <domain> <verb>`). Domains: `roles` (`export` / `diff` /
  `check` / `apply [--yes] [--delete]` / `restore <snapshot>`),
  `snapshot fetch` (live guild → `data/roles_export.json`), `manifest`
  (`render` offline JSON → manifest, `lint` parse check — no discord
  connection needed). New domains live under `cazzubot/cli/` as one module
  exposing a `Domain`. Live verbs boot their own discord connection and
  work while the bot is offline; every `roles apply` snapshots the guild to
  `data/roles_backups/` first; `restore` re-applies a snapshot (never
  deletes). `python -m cazzubot.roles` remains as a backwards-compatible
  alias for the `roles` domain.
- Safety: `@everyone` and managed roles are never edited/deleted; roles
  at or above the bot's highest role are reported, and reordering is
  blocked only when such a role would actually move or a role would cross
  above the bot — managed roles (bots, boost, shop, linked) CAN be
  repositioned with manage_roles (verified empirically); deletions require
  `--delete`; `check` exits non-zero on drift for hooks.
- Export always writes the format cheatsheet with all valid permission
  flags at the top and a `# vim: ft=txt :` modeline at the bottom.
- Preset sections (`[preset name]` + flag lines) are terminated by a blank
  line or the next `[` header — this lets header-less role lines follow a
  preset (guilds without marker roles). The export always emits that blank.
