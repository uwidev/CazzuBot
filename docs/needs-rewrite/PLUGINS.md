How to add a feature plugin
===========================

This is the core workflow of the v2 architecture. A feature is **one folder**;
everything it needs lives inside it. No central registration anywhere.


The contract
------------

Create `plugins/myfeature/__init__.py`:

~~~~ python
from cazzubot import Plugin


class MyFeature(Plugin):
    name = "myfeature"  # unique id (defaults to folder name)
    extensions = ["plugins.myfeature.extension"]  # lightbulb module(s)
    schema = [  # DDL, idempotent, runs at boot
        "CREATE TABLE IF NOT EXISTS myfeature (key TEXT PRIMARY KEY, value TEXT)",
    ]
    scheduled = {
        "mytag": my_due_handler
    }  # tag -> async handler(bot, payload)
    asset_decl = {MyAsset: "assets/myasset.png"}  # optional enum -> file
    item_decl = (
        MyItemEnum  # optional enum whose values are Item definitions
    )
    items_consumable = (
        True  # optional: gates this plugin's item consumption
    )
    depends_on = ("otherplugin",)  # names this plugin needs loaded first;
    # transitively expanded — see "Dependencies and sandbox mode" below
    enabled = False  # optional: ship disabled (mod does — see below)

    async def on_load(self, bot):
        """Optional startup hook (after every plugin's schema/extensions are ready)."""

    async def on_unload(self, bot):
        """Optional teardown hook."""


plugin = MyFeature()
~~~~

Commands live in a lightbulb extension module (`plugins/myfeature/extension.py`)
with a module-level `loader = lightbulb.Loader()`; class-based commands are
registered with `@loader.command`, listeners with `@loader.listener`, and
the group with `loader.command(my_group)`:

~~~~ python
import lightbulb

loader = lightbulb.Loader()

hello = lightbulb.Group("hello", "Greetings.")


@hello.register
class Hello(lightbulb.SlashCommand, name="world", description="Say hi."):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond("world")


loader.command(hello)
~~~~

The bot is reachable from commands as `ctx.client.app` (the `CazzuBot`) and
from listeners as `event.app`. Restart (or `/plugin reload myfeature` if dev
is loaded) — done.

For very small features, a single module `plugins/myfeature.py` with the same
`plugin = MyFeature()` line works too.


Dependencies and sandbox mode
-----------------------------

A plugin that reaches into another plugin's modules (a
`from plugins.x import ...` anywhere in its tree) declares that with
`depends_on = ("x", ...)` — the names of the plugins it needs loaded. At boot,
`select_plugins` (`cazzubot/plugin.py`) resolves the selection:

 -  **Transitive closure** — `-s myfeature` loads myfeature *and* everything
    it depends on, recursively. Unknown names abort the boot with the list of
    available plugins.
 -  **Cycles load together** — plugins that depend on each other (e.g.
    experience ↔ ranks, via `present_ranks` vs `of_member`) form one
    strongly-connected component and always load as a unit.
 -  **Dependency order** — the selected plugins load dependencies-first
    (topological sort), so boot no longer relies on alphabetical luck.

Declared today: `experience → (levels, ranks)`, `levels → (ranks,)`,
`ranks → (experience,)`, `frogs → (experience,)`.

Sandbox mode (`uv run python main.py -d -s [PLUGIN ...]`) loads **only** the
named plugins plus their transitive dependencies — nothing else. A bare
`-s` keeps the classic defaults (`poll`, `dev`). Production boots are
unaffected; the same dependency ordering applies to the full plugin set.
A disabled plugin requested in sandbox refuses to boot with guidance
(enable it first with `plugin enable`, or drop it from `-s`).


Enabling and disabling plugins
------------------------------

Every plugin has an **enabled flag**: the `Plugin.enabled` class
attribute is the code default (`True`), and the
`plugin.enabled.<name>` settings key overrides it. A plugin that ships
`enabled = False` (mod, today) does not load at boot unless the owner
enables it.

 -  **At boot**, disabled plugins are skipped — and so is everything that
    transitively depends on one (a disabled provider would leave its
    dependents half-wired). Skips are logged with the reason.
 -  **At runtime** (owner), the `plugin` group in the dev plugin manages the
    flag and the running bot:
     -  `plugin enable <name>` — persists `plugin.enabled.<name> = true` and
        loads the plugin with its dependency chain.
     -  `plugin disable <name>` — persists `false` and unloads the plugin with
        its loaded dependents.
     -  `plugin list` — every plugin with its ✅ loaded / ⛔ disabled / ⬜ not
        loaded state.
 -  The flag survives restarts. `plugin load`/`plugin unload` remain the
    session-only overrides (no flag change); `plugin enable`/`plugin disable`
    are the persisted switches.


Services available on the bot
-----------------------------

Use these instead of reaching into internals:

 -  `bot.db` — sqlite queries:
    `await bot.db.fetchall("SELECT * FROM t WHERE x = ?", x)`,
    `await bot.db.execute(...)`, `bot.db.transaction()` for multi-statement
    writes
 -  `bot.settings` — JSON key-value store, namespace your keys:
    `await bot.settings.get("myfeature.flag", False)`,
    `await bot.settings.set(...)`
 -  `bot.scheduler` — delayed tasks that survive restarts:
    `await bot.scheduler.add("mytag", when, {"payload": 1})`; register the tag
    in `scheduled`. The handler re-schedules by adding a new row.
 -  `bot.events` — typed domain event bus (observations between plugins):
    `bot.events.on(EventType, handler)` returns an **unsubscribe token**;
    `bot.events.off(EventType, handler)` withdraws. Defer subscriptions to the
    lifecycle so unload detaches them.
 -  `bot.inventory` / `bot.items` — the two halves of inventory:
    `bot.inventory` is the generic `(uid, item, qty)` ledger with the explicit
    `add` (+1) / `remove` (−1) / `modify` (signed delta) primitives (stacks
    prune at zero) plus `get`/`rows`/`rows_indexed`/`total`/`move_all`.
    `bot.items` is the **definitions layer**: what each stored `item_id` *is* —
    its icon/display name and its **item-owned consume** behavior (see
    `docs/ITEMS.md`). A plugin declares its item definitions with
    `item_decl = SomeEnum` (each member's value is an `Item`; the immutable
    `item_id` is the ledger oracle, so renaming the member/name is free) and
    `items_consumable` gates whether they may be consumed — independent of the
    `enabled` behavior flag, so a behavior-disabled plugin keeps its holdings
    visible/consumable. Frogs and exp use these directly — don't build
    per-feature tables for these shapes. The generic
    `/inventory view` / `/inventory consume <slot>` commands are in
    `plugins/inventory/`.
 -  `bot.effects` — the **seam / contribution store** (see
    `docs/needs-rewrite/EFFECTS.md`): scope-aware persistent modifiers with
    typed `SeamKey` seams, EXTEND/REPLACE reapply, lazy expiry, and scheduled
    world-convergence for external seams (Discord side effects like role
    grants). **Ownership (2026-08-28): the ITEM composes, effects modify** —
    an item's consume grants its own exp and applies the modifiers it
    declares; the modifier registry (`plugins/frogs/effects.py::EffectKey`)
    is a generic, scope-aware primitive library any caller can invoke.
    Frogs consume through two live seams: `FrogSeam.FROG_REACTION`
    (internal — the `plugins/frogs/reactions.py` listener rolls the
    per-message chance on the strongest live contribution, 10s in-memory
    cooldown, no-op until the emoji is published) and
    `FrogSeam.CLASSY_ROLE` (external — `RoleConverger` registered at
    plugin load adds/removes the classy role; `EffectsClearedEvent`
    reverts instantly). Cluster's spawn explosion is a spawn-side hook
    (`ClusterEffect`, `spawn_impl` injected at load — the edge
    `effects → factory` would cycle through species). `EffectKey.EXP`
    stays as the vestigial pre-composition fossil, composed into nothing.
 -  `bot.lifecycle` — declare effect undos (see “Conventions” below).
 -  `bot.assets` — enum-declared asset files (reconcile + kind-based sync to
    the asset child-guild: media CDN blobs + custom emoji); see
    `docs/ASSETS.md`.
 -  `bot.config` — `token`, `owner_id`, `guild_id`, `debug`, `sandbox`
 -  `bot.guild` — the one guild this bot serves


Conventions
-----------

 -  One plugin = one feature. Split big features into `db.py` (queries/schema),
    `extension.py` (lightbulb extension), `logic.py` (pure logic) inside the
    plugin folder.
 -  **Lifecycle — declare your undos.** Every runtime effect (scheduler rows,
    subscriptions, messages you must later delete) should hand its inverse to
    `bot.lifecycle.defer(plugin_name, undo)` at the point of application —
    usually in `on_load`. `load_plugin` already defers your `scheduled` tags
    and extensions automatically; unload replays undos in reverse and never
    touches durable data. **State-backed scheduling**: task rows are
    *projections*, not the source of truth — unload drops them, so `on_load`
    re-arms pending work from state. The full contract (withdrawal ordering,
    the mod expiry re-arm worked example) is one file:
    `docs/PLUGIN_ARCHITECTURE.md`.
 -  **CSR boundary:** service (`logic.py`/`factory.py`) and repository (`db.py`)
    modules take `db`/`settings` + plain values (+ injected `now`) and must
    **not** `import discord` or `hikari` — framework objects cross only the
    controller boundary. Enforced by `tests/core/test_csr_boundary.py` (the
    test fakes and the cazzubot core are checked too; the CLI engine is the
    allowlisted remainder until the CLI port).
 -  Enums are stored as TEXT; timestamps as ISO-8601 UTC strings; dicts/lists as
    JSON text (see `bot.db.dump_json` / `load_json`).
 -  No `gid` columns — this bot serves one guild. Check `bot.config.guild_id`
    where it matters.
 -  Prefix settings with the plugin name to avoid collisions in `settings`.
 -  Message templates (level-up, rank-up, frog, welcome) go through
    `cazzubot.templates.verify` / `prepare` so they stay jsonschema-validated.
 -  Format with `ruff format` (spaces, line-length 75) and run `ruff check`.


Channels plugin — declarative channel manifest
----------------------------------------------

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

~~~~
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
~~~~

 -  Covered Overview fields: name, type, category, position, slowmode,
    nsfw, bitrate, user limit, region, video quality. **Not managed**: the
    channel topic and permission overwrites. Voice attrs omitted from a
    line mean the Discord defaults (64 kbps, unlimited, auto).
 -  Renames: write `Old Name->New Name : tokens` — the live channel is
    renamed (the manifest line is rewritten to just `New Name : tokens`
    after a successful apply). A rename whose new name already exists is a
    conflict and blocks apply. `diff` also suggests read-only “did you mean
    rename?” hints.
 -  Type conversions: only `text <-> announcement` can be applied in place;
    any other kind change is reported as an unsupported type change and
    blocks apply (delete+recreate manually).
 -  Layout model: Discord keeps two independent position spaces per parent
    (text-section: text/announcement/forum; voice-section: voice/stage);
    the manifest order within a category only matters within each section.
 -  Engine (pure, offline-tested): `cazzubot.channels.parser`,
    `cazzubot.channels.export`, `cazzubot.channels.plan`. Executor (live):
    `cazzubot.channels.executor`.
 -  Admin CLI — `uv run cazzubot-cli channels <verb>` (or
    `uv run python -m cazzubot.cli channels <verb>`): `export` / `diff` /
    `check` / `apply [--yes] [--delete]` / `restore <snapshot>`, all with a
    `--scope-below <Category>` flag that limits management to one category and
    everything after it in the manifest — groups above are reported as out of
    scope and never touched. Live verbs boot their own discord connection and
    work while the bot is offline; every `channels apply` snapshots the guild
    to `data/channels_backups/` first; `restore` re-applies a snapshot (never
    deletes). `python -m cazzubot.channels` remains as a backwards-compatible
    alias.
 -  Safety: categories with children are never deleted (even with
    `--delete` — their children would go with them); an *empty* stray
    category is a `--delete` candidate. Deletions require `--delete`;
    stray channels are kept as-is; `check` exits non-zero on drift for
    hooks. The reorder only sends payloads for the scoped region, so
    out-of-scope channels keep their exact positions.
 -  Export always writes the format cheatsheet and a `# vim: ft=txt :`
    modeline at the bottom.


Frogs plugin — the five species
-------------------------------

`plugins/frogs/` is the frog economy: spawn → capture → inventory → consume,
per `docs/FROG.md`. Five species (weights): Basic (1000), Pog (200),
Froggers (50), Classy (200), Cluster (300). The species **entity**
(`species.py`) declares the world/spawn side only — name, rarity, weight,
art (Cluster has none), a catch effect, and an optional **spawn effect**
(Cluster's explosion). Consumption is **item-owned**: `items.py` holds the
`frog_exp` oracle (exp per species × state) beside `_SPECIES_CONSUME` — the
effect payloads the item applies (Pog/Froggers → the shared reaction
effect; Classy → the role grant; Basic → none; Cluster has **no item** —
uncatchable). Display (`/frog catalog`, the item info card) reads the same
sources as the grant, so they cannot drift.

 -  **Reaction listener** (`reactions.py`, guild-scoped message listener):
    an active `FROG_REACTION` contribution gives each message a chance the
    bot reacts with the froggers emoji (strongest live chance wins, 10s
    in-memory cooldown, no-op until the emoji is published).
 -  **Classy role** (`FrogSeam.CLASSY_ROLE`): `RoleEffect.consume`
    publishes the external seam; `RoleConverger` (registered at plugin
    load) adds the dev/prod classy role now and removes it at expiry; an
    explicit `EffectsClearedEvent` reverts instantly.
 -  **Cluster**: uncatchable; `Species.spawn_effect` short-circuits the
    spawn into 4–10 Basic frogs across the text channels ±2 around the
    spawn channel, staggered 0.75s (`ClusterEffect`; its `spawn_impl` —
    the factory's `spawn_and_wait` — is injected at load because
    `effects → factory` would cycle through species).
 -  **Quarterly reset** (`quarterly` tag): every frog becomes a Basic Frog
    (“use it or lose it”) — non-basic stacks fold into basic, then Basic's
    own normal→frozen devaluation runs.
 -  Conventional plugin structure: `species.py`/`effects.py`/`db.py` stay
    hikari-free (CSR); hikari lives in `factory.py` (the carve-out) and the
    new `reactions.py` listener module.


Roles plugin — declarative role manifest
----------------------------------------

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

~~~~
[Group]                 group-marker role (named "[Group]" on discord);
                        everything below it until the next marker belongs
                        to this group
Role Name               verbatim Discord name
Role Name : token …     tokens: hoist | mentionable | #rrggbb |
                        preset:<name> | +flag | -flag | icon:<emoji>
[preset name]           permission preset section; flag lines below it
# comment               blank lines and # comments are ignored
~~~~

 -  Final perms = preset ∪ `+flags` − `-flags`; a role with no tokens gets
    empty permissions. Names are verbatim (identity); `@everyone` is reserved.
 -  Renames: write `Old Name->New Name : tokens` on the role line — the live
    role is renamed (memberships survive) and the manifest line is rewritten
    to just `New Name : tokens` after a successful apply. A rename whose new
    name already exists is a conflict and blocks apply. `diff` also suggests
    read-only “did you mean rename?” hints for close delete+create pairs.
 -  Engine (pure, offline-tested): `cazzubot.roles.parser` (parse),
    `cazzubot.roles.export` (snapshot → manifest), `cazzubot.roles.plan`
    (diff → Plan). Executor (live): `cazzubot.roles.executor`.
 -  Admin CLI — single entry, one domain per feature:
    `uv run cazzubot-cli <domain> <verb>` (or
    `uv run python -m cazzubot.cli <domain> <verb>`). Domains: `roles`
    (`export` / `diff` / `check` / `apply [--yes] [--delete]` /
    `restore <snapshot>`), `snapshot fetch` (live guild →
    `data/roles_export.json`), `manifest` (`render` offline JSON → manifest,
    `lint` parse check — no discord connection needed). New domains live under
    `cazzubot/cli/` as one module exposing a `Domain`. Live verbs boot their
    own discord connection and work while the bot is offline; every
    `roles apply` snapshots the guild to `data/roles_backups/` first; `restore`
    re-applies a snapshot (never deletes). `python -m cazzubot.roles` remains
    as a backwards-compatible alias for the `roles` domain.
 -  Safety: `@everyone` and managed roles are never edited/deleted; roles
    at or above the bot's highest role are reported, and reordering is
    blocked only when such a role would actually move or a role would cross
    above the bot — managed roles (bots, boost, shop, linked) CAN be
    repositioned with manage\_roles (verified empirically); deletions require
    `--delete`; `check` exits non-zero on drift for hooks.
 -  Export always writes the format cheatsheet with all valid permission
    flags at the top and a `# vim: ft=txt :` modeline at the bottom.
 -  Preset sections (`[preset name]` + flag lines) are terminated by a blank
    line or the next `[` header — this lets header-less role lines follow a
    preset (guilds without marker roles). The export always emits that blank.
