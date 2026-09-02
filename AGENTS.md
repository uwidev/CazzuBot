CazzuBot
========

Discord bot for Club Cirno — v2 rewrite: plugin-based, SQLite, single guild.
Python 3.14 + hikari 2.5 + hikari-lightbulb 3.2 + aiosqlite, managed with uv.
Runs as `main.py`. Slash-only (guild-scoped).


Project
-------

 -  Entry point: `main.py` (`-d` debug, `-b/--bot` + `-g/--guild` side flags
    (default develop), `-s [PLUGIN ...]` sandbox = load only the named plugins
    plus their declared dependencies; bare `-s` = defaults poll/dev). Reads
    `TOKEN`/`TOKEN_DEV`, `OWNER_ID`, `GUILD_ID_PROD`/`GUILD_ID_DEV`,
    `DB_PATH_PROD`/`DB_PATH_DEV` from `.env` (see `.env.example`). Slash
    commands are guild-scoped (`default_enabled_guilds`).
 -  `cazzubot/` = core package (bot, config, db, errors, models, settings,
    scheduler, plugin loader, utils, levels, leaderboard, templates, timeparse,
    window) + the manifest engine: `cazzubot/manifest/` (shared roles/channels
    machinery) with the domain engines `cazzubot/roles/*` +
    `cazzubot/channels/*` and the admin CLI `cazzubot/cli/*`. `plugins/` = one
    folder per feature, auto-discovered; `board/`/`download/`/`emojis/` = asset
    dirs (gitignored).
 -  Per-guild sqlite files — `data/cazzubot-prod.db` (production) and
    `data/cazzubot-dev.db` (development), created on first boot — so
    development and production data never mix. To work against production data
    in the dev guild, clone the prod file over the dev one; the runtime guild
    gates (below) keep the bot within its configured guild either way.
    PG→SQLite migration tooling still lives in `scripts/`
    (migrate\_pg\_to\_sqlite.py, verify\_migration.py,
    boot\_check\_migrated.py; see docs/MIGRATION.md) and may run again.
    In-place SQLite migrations (new columns, re-keys, table rebuilds) are
    modules in `scripts/migrations/` run through the shared harness
    `python scripts/migrate.py` (dry-run by default, backup before write; see
    docs/add-a-migration.md).
 -  Design docs: `docs/ARCHITECTURE.md`, `docs/PLUGINS.md`,
    `docs/PLUGIN_ARCHITECTURE.md`, `docs/SYSTEMS.md`, `docs/TESTING.md`,
    `docs/MIGRATION.md`, `docs/MANUAL_TEST.md`. **Read PLUGINS.md before adding
    a feature.** README.md is a quick orientation with a full docs index.


Commands
--------

 -  Install: `uv sync`
 -  Run: `uv run python main.py -d` (default develop bot+guild) /
    `-b production -g production` (prod bot + prod guild) / `-s [PLUGIN ...]`
    (sandbox; bare `-s` = poll+dev)
 -  Admin CLI: `uv run cazzubot-cli <domain> <verb>` — domains
    `roles`/`channels` (export/diff/check/apply/restore), `snapshot` (fetch),
    `manifest` (offline render/lint). `--bot production --guild production`
    targets the production bot + production guild; no flags = development bot +
    development guild (default). Default `--file`/backup paths point at the
    production manifests — always use a temp `--file` during development-guild
    tests.
 -  Lint: `uv run ruff check .` — Format: `uv run ruff format .` — Types:
    `uv run basedpyright`
 -  Tests: `uv run pytest` — offline unit/integration tests. Per-feature tests
    in `tests/`, booted-bot fixtures in `tests/conftest.py`, typed hikari fakes
    in `tests/fakes.py`. Interaction flows (buttons/modals/slash pipeline) run
    end-to-end offline via `tests/driver.py`
    (`run_slash`/`press_button`/`submit_modal` through the real lightbulb
    routing; `full_bot` fixture boots every plugin). Verify interactive changes
    there, not just with direct handler calls. See `docs/TESTING.md` for the
    layered picture and what still needs live verification.


Working loop
------------

How to spend the fewest turns per feature (user preference, 2026-09). The blast
zone is intentional and cheap when verified narrowly; the full suite is ~717
tests / ~13s and only runs at run end.

 -  **Slice:** implement one feature slice with its tests. In-code docs
    (docstrings, caller/subscriber comments) always in scope; external project
    docs (`docs/*.md`, README, GLOSSARY, changelogs) ONLY when the user
    explicitly asks, as the final step of that run.
 -  **Per turn, verify narrowly:** run only the tests the slice touches —
    `tests/plugins/<feature>`, its
    `tests/integration/test_<feature>_driver.py`, and any changed `tests/core`
    file — plus `uv run ruff check .` and basedpyright. Not the full suite.
 -  **Run end:** when the user calls the run done, `uv run pytest` (full suite)
    once — as a background job while wrapping up — and report it once.
 -  **Turn finales are short:** don't re-verify unchanged work, don't
    re-litigate settled decisions.


Architecture
------------

 -  `cazzubot/bot.py` — `CazzuBot(hikari.GatewayBot)` + a lightbulb
    `GatewayEnabledClient`: owns `config`, `db`, `settings`, `scheduler`,
    `plugins`; two-phase plugin load (schemas+extensions first, then `on_load`
    hooks — no load-order deps); `verify_schema` boot guard; debug gating as a
    CHECKS hook; `UserInputError` unwrap in the client error handler.
 -  `cazzubot/db.py` — `Database`: aiosqlite wrapper (WAL, FK on, explicit
    `transaction()`), `execute/fetchall/fetchone/fetchval/executemany`,
    `dump_json/load_json`, `verify_schema` (boot-time drift check: DB schema
    must match the Python DDL exactly, extra tables allowed; mismatch → boot
    aborts). Enums → TEXT, timestamps → ISO-8601 UTC.
 -  `cazzubot/plugin.py` — `Plugin` base (`name`, `extensions` — import paths
    of lightbulb extension modules with a `loader = lightbulb.Loader()`,
    `schema`, `scheduled`, `on_load`/`on_unload`) + `discover_plugins()` and
    `load_plugin_module()` (packages or single modules; each defines
    `plugin = MyPlugin()`).
 -  `cazzubot/scheduler.py` — one loop over `tasks(tag, run_at, payload)`; tags
    registered via `Plugin.scheduled`; handlers re-schedule by inserting rows.
    Replaces frog/counter/mod expiry loops.
 -  `cazzubot/settings.py` — JSON key-value store (single guild), namespaced
    keys (e.g. `frog.enabled`, `rank.seasonal.message`, `level.quiet`).
 -  `cazzubot/window.py` — buffered, level-tagged command reporting to Discord
    (`command_window(ctx)` CM, `@windowed` decorator, `window_*` one-off
    helpers); auto-flushes at end of command and on error; ephemeral on slash.
    Distinct from CLI logging.
 -  Manifest engine — the roles/channels CLIs share one core:
    `cazzubot/manifest/lines.py` (parser machinery:
    Issue/ManifestError/rewrite\_renames/split\_name\_line/parse\_rename/validate\_renames/commit\_group),
    `plan.py` (UpdateOp/RenameOp, rename\_hints, render blocks), `executor.py`
    (ApplyResult, snapshot JSON I/O, backup\_path, REORDER\_ATTEMPTS), `cli.py`
    (the five verbs driven by a `ManifestDomain` spec). The domain engines hold
    the parser specs, plan diffing and apply bodies;
    `cazzubot/cli/{roles,channels,snapshot,manifest}.py` are thin wiring
    shells. New domains = one module under `cazzubot/cli/` exposing a `Domain`.
 -  Plugins: experience (message exp pipeline + membership card + `exp top`
    paging), levels, ranks (thresholds → roles, seasonal/lifetime), frogs
    (spawn cadence `interval ± fuzzy%`, capture, consume-for-exp; owns the
    `quarterly` freeze and `daily.frog` capture resync cadences), mod (modlog +
    scheduled mute/tempban; **ships disabled** — incomplete, moderation handled
    by other bots), poll (app commands + modal view), welcome, counter (baka
    button), fun (memes: echo/ping/noot/inktober/write), board (weekly image
    scrape → numbered grid: `/board scrape`/`post`), misc (server utilities:
    banner/welcome/week), roles + channels (warn-only boot drift-check for the
    manifests), dev (owner tools +
    `plugin reload`/`load`/`unload`/`enable`/`disable`/`list`).
 -  Cross-plugin flow: `experience.on_message` awards exp then calls
    `plugins.levels.presenter.present_level_up` and
    `plugins.ranks.presenter.present_ranks` (the pure decisions live in
    `levels.logic.decide_level_up` / `ranks.logic.plan_rank_changes`).


Conventions
-----------

 -  **Spaces**, double quotes, line-length 75 (`ruff format`). Run `ruff check`
    after edits.
 -  Variable naming: common noun first, variant suffix always last —
    `SCRAPE_CHANNEL_DEV`/`SCRAPE_CHANNEL_PROD`, never
    `DEV_SCRAPE_CHANNEL`/`PROD_SCRAPE_CHANNEL`. Applies to any paired
    constants/variables (dev/prod, prod/sandbox, left/right, …).
 -  Scripts and CLI modules are organized top-down by abstraction: docstring →
    imports → constants → core/top-level functions first → helpers toward the
    bottom → `if __name__ == "__main__":` guard last (see
    `cazzubot/cli/roles.py`).
 -  Non-`.txt` custom-format files (`roles.manifest`, `channels.manifest`) end
    with a `# vim: ft=txt :` modeline on the last line.
 -  **Guild isolation:** the gateway streams events from every guild the token
    belongs to, but the bot serves ONE guild. Guild-scoped listeners MUST be
    registered with `cazzubot.listeners.guild_listener(loader, event_type)`
    (never bare `@loader.listener`) — it drops other-guild/DM events before the
    handler runs; scheduler payloads that target channels (frog spawns, counter
    expiry) are guarded with `utils.channel_in_guild`. New guild-scoped
    listeners that skip the helper are a bug.
 -  Service modules (`logic.py`/`factory.py`/`db.py`) never import discord —
    enforced by `tests/core/test_csr_boundary.py` (only carve-out:
    `plugins/frogs/factory.py`, controller-shaped by design). Service/core
    validation errors raise `cazzubot.errors.UserInputError`; the lightbulb
    error handler in bot.py translates them (and `ConversionFailedException`)
    into ephemeral replies.
    Framework-agnostic member values travel as `cazzubot.models.MemberSnapshot`.
 -  Plugins reach services via `bot.db`, `bot.settings`, `bot.scheduler`,
    `bot.config`, `bot.guild`. Plugin db modules take `db: Database` (or
    `settings: Settings`) as first arg; extension modules use `ctx.client.app`
    (the `CazzuBot`) and listeners get it from `event.app`.
 -  No `gid` columns anywhere; no FK decorators;
    `INSERT OR IGNORE`/`INSERT OR REPLACE` for idempotent writes.
 -  **Model boundary for reads:** row fetches return dataclasses —
    `row_to`/`rows_to` (via `fetch_model`/`fetch_models`) coerce stored
    TEXT/INTEGER to the declared field types (`pendulum.DateTime`, enums, JSON
    dicts/lists, bool); raw `aiosqlite.Row`/`Any` never crosses a
    db-module/public API boundary (enforced by
    `tests/core/test_db_boundary.py`; `cazzubot/settings.py` is the
    untyped-JSON carve-out). One dataclass per row shape, promoted to a shared
    model when a shape repeats; projections/scalars stay precise tuples/scalars.
 -  All delayed work goes through the central scheduler, re-armed on due and on
    `on_load` (missed-run force checks on boot): tags `daily` (experience — exp
    resets) / `daily.frog` + `quarterly` (frogs — capture resync + season
    freeze) / `frog` / `modlog` / `counter`. The daily/quarterly wrapper
    plugins no longer exist; each cadence lives in the plugin that owns its
    data.
 -  User-configurable message JSON goes through `cazzubot.templates.verify`
    (jsonschema-validated), is readied by `prepare`, and delivered by `send`
    (single `embed`/`embeds`/empty-content handling, any send target);
    placeholders applied via `utils.deep_map` + per-feature formatters.
 -  Time handled with pendulum, always UTC (see `cazzubot/timeparse.py`).
 -  Command feedback goes through `cazzubot.window` (levels
    debug/info/success/warn/error; success/warn/error prefix ✓/⚠︎/✖) — no
    emoji-reaction feedback. CLI `logging` stays for bot internals (db,
    connection, plugin hooks); command-local state goes to the user via the
    window, flushed before blocking ops and always at command end (even on
    error).
 -  Ruff select `["E4", "E7", "E9", "F"]`; basedpyright config present (Python
    3.14, Linux, recommended mode with rule overrides for the dynamic layers).


Design principles
-----------------

 -  **Minimum friction to build on.** Infrastructure and code are designed
    and implemented so that modifying them or building on top of them costs
    as little as possible: prefer isolated, atomic, modular shapes (one
    feature = one folder, service/repository/controller splits, typed
    registries, one table per concern) whenever the overhead stays
    reasonable. An abstraction that makes the common modification harder is
    a net loss — this is the lesson of the v1 rewrite (see
    `docs/ARCHITECTURE.md`). Least friction wins over cleverness.
 -  **Self-documenting code.** Code should explain itself; understanding it
    should not require an external document. When the call graph is
    ambiguous — what calls a method, who emits an event, who invokes a
    handler — name it in a comment at the ambiguous point: event emitters
    state their subscribers, bus handlers state who invokes them, entry
    points state their callers. If a reader has to hunt for “what pulls
    this”, the code is missing a comment.


Notes
-----

 -  `frog register`/`exp`/`rank`/`level`/`welcome`/`frog set` require admin;
    `consume` confirms via a Yes/No button view (`cazzubot.utils.ConfirmMenu`).
 -  Command security: every admin/owner command is hidden from non-admins via
    `default_member_permissions=hikari.Permissions.ADMINISTRATOR` where the
    framework allows (fully-gated groups:
    `board`/`counter`/`level`/`rank`/`welcome`/`poll`/`misc`/`story` + dev's
    `calc`/`plugin`; top-level: dev `owner`/`archive_emojis`/`scrape`, fun
    `register_inktober`/`scrape_inktober`) and always carries an execution
    hook. Mixed groups (`frog`/`exp`/`mod`) stay visible because subcommands
    can't carry the field, but every mutating subcommand is check-gated.
    Enforced by `tests/core/test_command_guards.py` (whole-tree sweep: every
    command must be hidden, hook-checked, or explicitly user-facing) and
    `tests/integration/test_guard_driver.py` (real-pipeline block/allow).
 -  Deploy: `push_to_prod.sh` (untracked, machine-specific).


Guild safety
------------

 -  **Production guild `293796316193095690` (Club Cirno) is NEVER mutated** —
    no role/channel/emoji changes, no `roles apply`, unless the user
    explicitly authorizes it (per-turn, per-operation). Read-only commands
    (`roles diff`/`check`, `snapshot fetch`) are fine.
 -  **Development guild `408801760581386245` is free to mutate** for
    CLI/testing validation. The CLI defaults to the development bot + guild
    (no flags needed): `uv run cazzubot-cli …`.
    Always point `--file` at a temp manifest during development-guild tests
    so the production `roles.manifest` and `data/roles_export.json` aren't
    clobbered.
