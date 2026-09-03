CazzuBot
========

Discord bot for Club Cirno — v2 rewrite: plugin-based, SQLite, single guild.
Python 3.14 + hikari 2.5 + hikari-lightbulb 3.2 + aiosqlite, managed with uv.
Runs as `main.py`. Slash-only (guild-scoped).


Entry point & running
---------------------

 -  `main.py -d` — develop bot + develop guild (default).
 -  `-b production -g production` — production bot + production guild.
 -  `-s [PLUGIN ...]` — sandbox: load only named plugins plus declared
    dependencies; bare `-s` = defaults poll/dev.
 -  Reads `TOKEN`/`TOKEN_DEV`, `OWNER_ID`, `GUILD_ID_PROD`/`GUILD_ID_DEV`,
    `DB_PATH_PROD`/`DB_PATH_DEV` from `.env` (see `.env.example`).
 -  Slash commands are guild-scoped (`default_enabled_guilds`).


Layout
------

```
main.py                    entry point
cazzubot/                  core package (bot, config, db, errors, …)
cazzubot/{items,inventory,statuses,assets,events,lifecycle,…}  game stores + lifecycle
cazzubot/manifest/         shared roles/channels manifest engine
cazzubot/cli/              admin CLI wiring (roles, channels, snapshot, manifest)
plugins/                   one folder per feature, auto-discovered
tests/                     offline tests (core/, plugins/, integration/)
tests/driver.py            e2e slash/button/modal pipeline driver (real lightbulb routing)
tests/fakes.py             typed hikari fakes + seed_bot()
docs/QUICKSTART.md         task-based walkthroughs index
docs/how-do-i/             step-by-step task guides
docs/SYSTEMS.md            one-page systems map
docs/GLOSSARY.md           stabilized vocabulary
docs/FROG.md               frog system design
docs/needs-rewrite/        older in-depth docs (being reworked)
docs/aegis/                Aegis workspace
CONTEXT.md                 canonical project terms
```


Commands
--------

 -  Install: `uv sync`
 -  Run: `uv run python main.py -d`
 -  Admin CLI: `uv run cazzubot-cli <domain> <verb>` — domains
    `roles`/`channels` (export/diff/check/apply/restore), `snapshot` (fetch),
    `manifest` (offline render/lint). No flags = develop bot+guild.
    Use a temp `--file` during dev-guild tests to avoid clobbering prod paths.
 -  Lint: `uv run ruff check .` — Format: `uv run ruff format .` — Types:
    `uv run basedpyright`
 -  Tests: `uv run pytest` — 717 tests / ~13s. Offline: no Discord connection.


Working loop
------------

How to spend the fewest turns per feature (user preference).

 -  **Slice:** implement one feature slice with its tests. In-code docs
    (docstrings, caller/subscriber comments) always in scope; external project
    docs (`docs/*.md`, README, GLOSSARY, changelogs) ONLY when the user
    explicitly asks per-run.
 -  **Per turn, verify narrowly:** run only the tests the slice touches —
    `tests/plugins/<feature>`, its `tests/integration/test_<feature>_driver.py`,
    and any changed `tests/core` file — plus `ruff check .` and basedpyright.
    Not the full suite.
 -  **Run end:** when the user calls the run done, `uv run pytest` (full suite)
    once — as a background job while wrapping up — and report it once.
 -  **Turn finales are short:** don't re-verify unchanged work, don't
    re-litigate settled decisions.


Architecture
------------

 -  **`cazzubot/bot.py`** — `CazzuBot(GatewayBot)` + lightbulb client: owns
    `config`, `db`, `settings`, `scheduler`, `plugins`, `items`, `assets`,
    `statuses`. Two-phase plugin load (schemas+extensions → `on_load` hooks);
    `verify_schema` boot guard; debug gating as CHECKS hook.
 -  **`cazzubot/db.py`** — `Database`: aiosqlite wrapper (WAL, FK on,
    explicit `transaction()`). `verify_schema` = boot-time drift check (exact
    DDL match; extra tables allowed; mismatch → boot aborts). Enums → TEXT,
    timestamps → ISO-8601 UTC.
 -  **`cazzubot/plugin.py`** — `Plugin` base: `name`, `extensions` (import
    paths of lightbulb extension modules), `schema`, `scheduled`,
    `on_load`/`on_unload`, `item_decl`, `depends_on`. Auto-discovered.
 -  **`cazzubot/items.py` + `inventory.py`** — item definitions registry
    (code-declared, id-resolvable) + inventory ledger (counts holdings by
    `item_id`). Consumption gated by per-provider flag.
 -  **`cazzubot/statuses.py`** — generic seam/contribution/pull store:
    scope-aware persistent contributions, feature-owned convergers (stock
    `RoleConverger`), lazy expiry (no sweeper). Replaces old member_effect.
 -  **`cazzubot/events.py`** — domain event bus (fastapi-style
    `@subscribe`/`emit`), typed event classes.
 -  **`cazzubot/scheduler.py`** — one loop over `tasks(tag, run_at, payload)`;
    tags registered via `Plugin.scheduled`; handlers re-schedule by inserting
    rows.
 -  **`cazzubot/settings.py`** — JSON key-value store (single guild),
    namespaced keys.
 -  **`cazzubot/window.py`** — buffered, level-tagged command reporting;
    auto-flushes on end/error; ephemeral on slash.
 -  **Manifest engine** — `cazzubot/manifest/` (parser/plan/executor/drift)
    shared by roles + channels domain engines; thin CLI shells in
    `cazzubot/cli/{roles,channels,snapshot,manifest}.py`.
 -  **Plugins** (current):
    `board` (weekly image scrape→grid), `counter` (baka button),
    `dev` (owner tools + plugin reload/load/unload/enable/disable/list),
    `experience` (message exp + leaderboards),
    `frogs` (spawn cadence, species compose behaviors, inventory items,
    statuses, quarterly freeze, cluster burst),
    `fun` (echo/ping/noot/inktober/write), `inventory` (view/consume),
    `levels` (thresholds→roles), `misc` (banner/welcome/week),
    `mod` (modlog + mute/tempban; **ships disabled**),
    `poll` (app commands + modal), `ranks` (seasonal/lifetime),
    `roles` + `channels` (warn-only boot drift-check), `welcome` (join messages).
 -  **Cross-plugin flow:** `experience.on_message` → `award_exp` →
    `levels.presenter.present_level_up` → `ranks.presenter.present_ranks`;
    items/statuses flow through `bot.items` / `bot.statuses` / inventory.


Conventions
-----------

 -  **Spaces**, double quotes, line-length 75 (`ruff format`). Ruff select
    `["E4", "E7", "E9", "F"]`.
 -  Variable naming: common noun first, variant suffix last —
    `SCRAPE_CHANNEL_DEV`/`SCRAPE_CHANNEL_PROD`, never the reverse.
 -  Scripts/CLI modules: top-down by abstraction (docstring → imports →
    constants → core functions → helpers → `if __name__ == "__main__":`).
 -  **Guild isolation:** guild-scoped listeners MUST use
    `cazzubot.listeners.guild_listener(loader, event_type)` (never bare
    `@loader.listener`); scheduler payloads guarded with
    `utils.channel_in_guild`. Skipping the helper is a bug.
 -  **Model boundary for reads:** row fetches return dataclasses via
    `fetch_model`/`fetch_models`; raw `aiosqlite.Row` never crosses a
    db-module/public API boundary (enforced by test; `settings.py` carve-out).
    No `gid` columns; `INSERT OR IGNORE`/`INSERT OR REPLACE` for idempotent
    writes.
 -  Service/core modules (`logic.py`/`db.py`/`factory.py`) never import
    discord (enforced by `tests/core/test_csr_boundary.py`; frogs factory
    is the only carve-out). Validation errors raise `UserInputError`.
 -  Framework-agnostic member data travels as `MemberSnapshot`.
 -  All delayed work through the central scheduler, re-armed on due and
    `on_load`: tags `daily` / `daily.frog` / `quarterly` / `frog` / `modlog` /
    `counter` / `statuses.converge`.
 -  User-configurable message JSON: `templates.verify` (jsonschema) →
    `prepare` → `send`; placeholders via `deep_map` + per-feature formatters.
 -  Time: pendulum, always UTC.
 -  Command feedback through `cazzubot.window` (debug/info/success/warn/error,
    prefix ✓/⚠︎/✖) — no emoji-reaction feedback.
 -  Statuses: items compose status classes (via `bot.statuses`), never the
    reverse. Species compose behaviors (plain async callables for catch/spawn).


Design principles
-----------------

 -  **Minimum friction to build on.** Isolated, atomic, modular shapes (one
    feature = one folder, one table per concern) whenever the overhead stays
    reasonable. Least friction wins over cleverness.
 -  **Self-documenting code.** When the call graph is ambiguous — event
    emitters state subscribers, bus handlers state callers, entry points
    state callers. If a reader has to hunt for "what pulls this", the code
    is missing a comment.


Guild safety
------------

 -  **Production guild `293796316193095690` (Club Cirno) is NEVER mutated** —
    no role/channel/emoji changes, no `roles apply`, unless the user
    explicitly authorizes it per-turn. Read-only commands are fine.
 -  **Development guild `408801760581386245` is free to mutate** for
    CLI/testing validation. CLI defaults to develop bot+guild.
    Always point `--file` at a temp manifest during dev-guild tests.
 -  Production files (`/mnt/tmp/CazzuBot`) are never modified unless the
    user explicitly allows it per-turn. All work lives on `main`.
 -  This repo is worked on by parallel agent sessions — `git status` +
    file mtimes before claiming suite state.