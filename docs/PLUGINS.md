# How to add a feature plugin

This is the core workflow of the v2 architecture. A feature is **one folder**;
everything it needs lives inside it. No central registration anywhere.

## The contract

Create `plugins/myfeature/__init__.py`:

```python
from cazzubot import Plugin


class MyFeature(Plugin):
    name = "myfeature"  # unique id (defaults to folder name)
    extensions = ["plugins.myfeature.cog"]  # lightbulb extension module(s)
    schema = [  # DDL, idempotent, runs at boot
        "CREATE TABLE IF NOT EXISTS myfeature (key TEXT PRIMARY KEY, value TEXT)",
    ]
    scheduled = {
        "mytag": my_due_handler
    }  # tag -> async handler(bot, payload)
    depends_on = ("otherplugin",)  # names this plugin needs loaded first;
    # transitively expanded — see "Dependencies and sandbox mode" below

    async def on_load(self, bot):
        """Optional startup hook (after every plugin's schema/extensions are ready)."""

    async def on_unload(self, bot):
        """Optional teardown hook."""


plugin = MyFeature()
```

Commands live in a lightbulb extension module (`plugins/myfeature/cog.py`)
with a module-level `loader = lightbulb.Loader()`; class-based commands are
registered with `@loader.command`, listeners with `@loader.listener`, and
the group with `loader.command(my_group)`:

```python
import lightbulb

loader = lightbulb.Loader()

hello = lightbulb.Group("hello", "Greetings.")


@hello.register
class Hello(lightbulb.SlashCommand, name="world", description="Say hi."):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond("world")


loader.command(hello)
```

The bot is reachable from commands as `ctx.client.app` (the `CazzuBot`) and
from listeners as `event.app`. Restart (or `/cog reload myfeature` if dev
is loaded) — done.

For very small features, a single module `plugins/myfeature.py` with the same
`plugin = MyFeature()` line works too.

## Dependencies and sandbox mode

A plugin that reaches into another plugin's modules (a `from plugins.x import
...` anywhere in its tree) declares that with `depends_on = ("x", ...)` —
the names of the plugins it needs loaded. At boot, `select_plugins`
(`cazzubot/plugin.py`) resolves the selection:

- **Transitive closure** — `-s myfeature` loads myfeature *and* everything
  it depends on, recursively. Unknown names abort the boot with the list of
  available plugins.
- **Cycles load together** — plugins that depend on each other (e.g.
  experience ↔ ranks, via `present_ranks` vs `of_member`) form one
  strongly-connected component and always load as a unit.
- **Dependency order** — the selected plugins load dependencies-first
  (topological sort), so boot no longer relies on alphabetical luck.

Declared today: `experience → (levels, ranks)`, `levels → (ranks,)`,
`ranks → (experience,)`, `frogs → (experience,)`.

Sandbox mode (`uv run python main.py -d -s [PLUGIN ...]`) loads **only** the
named plugins plus their transitive dependencies — nothing else. A bare
`-s` keeps the classic defaults (`poll`, `dev`). Production boots are
unaffected; the same dependency ordering applies to the full plugin set.

## Services available on the bot

Use these instead of reaching into internals:

- `bot.db` — sqlite queries:
  `await bot.db.fetchall("SELECT * FROM t WHERE x = ?", x)`,
  `await bot.db.execute(...)`, `bot.db.transaction()` for multi-statement writes
- `bot.settings` — JSON key-value store, namespace your keys:
  `await bot.settings.get("myfeature.flag", False)`, `await bot.settings.set(...)`
- `bot.scheduler` — delayed tasks that survive restarts:
  `await bot.scheduler.add("mytag", when, {"payload": 1})`; register the tag in
  `scheduled`. The handler re-schedules by adding a new row.
- `bot.events` — typed domain event bus (observations between plugins):
  `bot.events.on(EventType, handler)` returns an **unsubscribe token**;
  `bot.events.off(EventType, handler)` withdraws. Defer subscriptions to the
  lifecycle so unload detaches them.
- `bot.inventory` / `bot.member_effects` — the generic game stores (see
  `docs/ROADMAP.md` "Data model").
- `bot.lifecycle` — declare effect undos (see below).
- `bot.config` — `token`, `owner_id`, `guild_id`, `debug`, `sandbox`
- `bot.guild` — the one guild this bot serves

## Conventions

- One plugin = one feature. Split big features into `db.py` (queries/schema),
  `cog.py` (lightbulb extension), `logic.py` (pure logic) inside the plugin
  folder.
- **Lifecycle — declare your undos.** Every runtime effect (scheduler rows,
  subscriptions, messages you must later delete) should hand its inverse to
  `bot.lifecycle.defer(plugin_name, undo)` at the point of application —
  usually in `on_load`. `load_plugin` already defers your `scheduled` tags
  and extensions automatically; unload replays undos in reverse and never
  touches durable data. See `docs/PLUGIN_ARCHITECTURE.md`.
- **State-backed scheduling.** Scheduled task rows are *projections* of your
  data or declarations, not the source of truth: unload drops them, so your
  `on_load` must re-arm pending work from state (cadences from your cadence
  constant, one-shots from your tables — applying overdue work immediately).
  The mod plugin's expiry re-arm is the worked example.
- **CSR boundary:** service (`logic.py`/`factory.py`) and repository (`db.py`)
  modules take `db`/`settings` + plain values (+ injected `now`) and must
  **not** `import discord` or `hikari` — framework objects cross only the
  controller boundary. Enforced by `tests/core/test_csr_boundary.py` (the
  test fakes and the cazzubot core are checked too; the CLI engine is the
  allowlisted remainder until the CLI port).
- Enums are stored as TEXT; timestamps as ISO-8601 UTC strings; dicts/lists as
  JSON text (see `bot.db.dump_json` / `load_json`).
- No `gid` columns — this bot serves one guild. Check `bot.config.guild_id`
  where it matters.
- Prefix settings with the plugin name to avoid collisions in `settings`.
- Message templates (level-up, rank-up, frog, welcome) go through
  `cazzubot.templates.verify` / `prepare` so they stay jsonschema-validated.
- Format with `ruff format` (tabs, line-length 75) and run `ruff check`.

## Channels plugin — declarative channel manifest

`plugins/channels/` hosts the **boot-time drift check only**. All
enforcement is manual via the CLI; the plugin never applies anything.

The manifest (`channels.manifest` at the repo root, committed) is the
source of truth for channel structure. Discord's **native grouping —
categories — is exactly what the manifest models**: a `[Category]` header
declares a Discord category, and everything below it until the next header
belongs to it. Channels before the first header are uncategorized (they
render at the top). **Order is positional**: an export writes every
channel in its exact rendering order and `diff`/`apply` enforce it. Line
format:

```
[Category]              category header — maps to a Discord category;
                        everything below it until the next header
                        belongs to it
Channel Name            verbatim Discord name (text unless a token says
                        otherwise)
Channel Name : token …  tokens: type:text|announcement|voice|forum|
                        stage (default text) | nsfw | slowmode:<sec> |
                        bitrate:<kbps> | limit:<n> |
                        region:<code|auto> | quality:auto|1080
Old Name->New Name      rename a channel (rewritten to just the new name
                        after a successful apply)
# comment               blank lines and # comments are ignored
```

- Covered Overview fields: name, type, category, position, slowmode,
  nsfw, bitrate, user limit, region, video quality. **Not managed**: the
  channel topic and permission overwrites. Voice attrs omitted from a
  line mean the Discord defaults (64 kbps, unlimited, auto).
- Renames: write `Old Name->New Name : tokens` — the live channel is
  renamed (the manifest line is rewritten to just `New Name : tokens`
  after a successful apply). A rename whose new name already exists is a
  conflict and blocks apply. `diff` also suggests read-only "did you mean
  rename?" hints.
- Type conversions: only `text <-> announcement` can be applied in place;
  any other kind change is reported as an unsupported type change and
  blocks apply (delete+recreate manually).
- Layout model: Discord keeps two independent position spaces per parent
  (text-section: text/announcement/forum; voice-section: voice/stage);
  the manifest order within a category only matters within each section.
- Engine (pure, offline-tested): `cazzubot.channels.parser`,
  `cazzubot.channels.export`, `cazzubot.channels.plan`. Executor (live):
  `cazzubot.channels.executor`.
- Admin CLI — `uv run cazzubot-cli channels <verb>` (or `uv run python -m
  cazzubot.cli channels <verb>`): `export` / `diff` / `check` /
  `apply [--yes] [--delete]` / `restore <snapshot>`, all with a
  `--scope-below <Category>` flag that limits management to one category
  and everything after it in the manifest — groups above are reported as
  out of scope and never touched. Live verbs boot their own discord
  connection and work while the bot is offline; every `channels apply`
  snapshots the guild to `data/channels_backups/` first; `restore`
  re-applies a snapshot (never deletes). `python -m cazzubot.channels`
  remains as a backwards-compatible alias.
- Safety: categories with children are never deleted (even with
  `--delete` — their children would go with them); an *empty* stray
  category is a `--delete` candidate. Deletions require `--delete`;
  stray channels are kept as-is; `check` exits non-zero on drift for
  hooks. The reorder only sends payloads for the scoped region, so
  out-of-scope channels keep their exact positions.
- Export always writes the format cheatsheet and a `# vim: ft=txt :`
  modeline at the bottom.

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
