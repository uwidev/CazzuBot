CazzuBot — Systems
==================

One-page map of every system the code lays out: core services in `cazzubot/`,
the manifest engine + admin CLI, and feature plugins in `plugins/`. It is the
cross-system index only — the deep documentation lives in the code, one system
per module docstring, per the self-documenting rule in `AGENTS.md`. Keep this
page in sync when a system appears or disappears, or a dependency edge changes;
the per-module truth stays in the docstrings.

Task walkthroughs live in `docs/QUICKSTART.md` and `docs/how-do-i/`; what loads
when and why is in `AGENTS.md`. A rendered-friendly table version of this page
lives in `docs/SYSTEM-TABLED.md`.

Each system is a `###` heading — `name — code path` — with labeled fields
below, so every system is a jump target (`?^### <name>`, `]m` / `[m` in vim):

 -  `What:` — one-line description
 -  `Read first:` — systems worth understanding before this one; for plugins
    this is the code-level `depends_on` the loader enforces
 -  `Used by:` — systems that depend on this one

Fields are omitted when empty.

A suggested reading order:

1.  Plugin framework → bot core — how a plugin is declared, discovered, loaded
2.  Config → database → settings — what a boot needs underneath
3.  Scheduler → lifecycle → event bus → command window — the plumbing
4.  Effects → inventory → items → assets — the game stores
5.  A plugin you care about — features compose the above


Core services (`cazzubot/`)
---------------------------

### Plugin framework — `cazzubot/plugin.py`

 -  What: Plugin base, discovery, dependency selection
 -  Used by: bot, every plugin

### Bot core — `cazzubot/bot.py`

 -  What: CazzuBot: owns every service, boot order, load/unload/reload, error
    translation
 -  Read first: plugin framework, config
 -  Used by: main.py; every plugin (`ctx.client.app`)

### Config & bootstrap — `cazzubot/config.py`, `main.py`

 -  What: Env-driven Config, bot/guild sides, sandbox, logging
 -  Used by: bot, assets, CLI

### Database — `cazzubot/db.py`

 -  What: aiosqlite wrapper, `verify_schema`, typed model boundary
 -  Read first: config
 -  Used by: every store and plugin db module

### Settings — `cazzubot/settings.py`

 -  What: JSON key-value store, namespaced keys
 -  Read first: database
 -  Used by: bot (`plugin.enabled.*`), drift plugins, features

### Scheduler — `cazzubot/scheduler.py`

 -  What: DB-backed delayed tasks: tags, `At` cadences, retry policy
 -  Read first: database, timeparse
 -  Used by: bot (tags), effects (converge), timed plugins

### Lifecycle — `cazzubot/lifecycle.py`

 -  What: Per-plugin undo stacks; teardown is structural
 -  Read first: plugin framework
 -  Used by: bot (load/unload), events (unsubscribe tokens)

### Event bus — `cazzubot/events.py`

 -  What: Typed domain events, observer seam
 -  Read first: lifecycle
 -  Used by: frogs (emits); future observers

### Effects — `cazzubot/effects.py`

 -  What: Scope-aware contribution store + convergence jobs
 -  Read first: database, scheduler
 -  Used by: experience (pull); frogs (reaction + role seams)

### Inventory — `cazzubot/inventory.py`

 -  What: Per-member item quantity ledger
 -  Read first: database
 -  Used by: frogs (captures, season reset), inventory plugin

### Items — `cazzubot/items.py`

 -  What: Item-definition registry keyed by immutable id
 -  Read first: inventory
 -  Used by: bot (register), inventory plugin, frogs

### Assets — `cazzubot/assets.py`

 -  What: Typed asset registry, CDN/emoji publishing, boot reconcile
 -  Read first: database, config
 -  Used by: frogs (species art), inventory plugin (icons)

### Command window — `cazzubot/window.py`

 -  What: Buffered, level-tagged command reporting
 -  Used by: most command extensions

### Message templates — `cazzubot/templates.py`

 -  What: jsonschema-validated JSON message templates
 -  Read first: utils
 -  Used by: levels, ranks, frogs, welcome

### Guild isolation — `cazzubot/listeners.py`

 -  What: Guild-gated listeners and payload guards (`utils.in_guild` /
    `channel_in_guild`)
 -  Read first: bot, utils
 -  Used by: all plugin extensions

### Shared helpers — `cazzubot/utils.py`

 -  What: Permissions, seasons, `ConfirmMenu`, `deep_map`, snapshots
 -  Read first: bot, models
 -  Used by: essentially everything

### Shared models — `cazzubot/models.py`

 -  What: `MemberSnapshot` + enums stored as TEXT
 -  Used by: db modules, formatters

### Time parsing — `cazzubot/timeparse.py`

 -  What: Natural-language time/duration → UTC
 -  Used by: scheduler, frogs, mod

### Level math — `cazzubot/levels.py`

 -  What: Exp→level curve (memoized)
 -  Used by: experience, levels plugin

### Leaderboard — `cazzubot/leaderboard.py`

 -  What: Text scoreboard rendering
 -  Used by: experience (`exp top`), frogs


Manifest engine & admin CLI
---------------------------

### Manifest core — `cazzubot/manifest/`

 -  What: Shared line parsing, plan ops, apply plumbing, drift check
 -  Used by: roles/channels domains + plugins + CLI

### Roles domain — `cazzubot/roles/`

 -  What: `roles.manifest` parser/plan/apply/export
 -  Read first: manifest core
 -  Used by: CLI roles, roles plugin

### Channels domain — `cazzubot/channels/`

 -  What: `channels.manifest` parser/plan/apply/export
 -  Read first: manifest core
 -  Used by: CLI channels, channels plugin

### Admin CLI — `cazzubot/cli/`

 -  What: One entry, five verbs per domain
    (`roles`/`channels`/`snapshot`/`manifest`)
 -  Read first: manifest core + domains
 -  Used by: operators (manual enforcement)


Feature plugins (`plugins/`)
----------------------------

### experience — `plugins/experience/`

 -  What: Message exp pipeline, membership card, `exp top`
 -  Read first: levels, ranks
 -  Used by: frogs (consume sink), ranks (seasonal exp)

### levels — `plugins/levels/`

 -  What: Level thresholds + level-up presentation
 -  Read first: ranks
 -  Used by: experience (presents)

### ranks — `plugins/ranks/`

 -  What: Threshold roles, seasonal & lifetime
 -  Read first: experience
 -  Used by: experience, levels

### frogs — `plugins/frogs/`

 -  What: Spawn/capture/consume; five species items, effects, art;
    reaction listener; cluster spawn; season reset
 -  Read first: experience
 -  Used by: inventory, inventory plugin, assets, events

### inventory — `plugins/inventory/`

 -  What: `/inventory` view/consume over `bot.inventory` + `bot.items`
 -  Read first: inventory, items
 -  Used by: frogs (its items)

### board — `plugins/board/`

 -  What: Weekly scrape → numbered grid + vote poll
 -  Read first: poll, misc

### poll — `plugins/poll/`

 -  What: Poll commands + modal voting view
 -  Used by: board

### mod — `plugins/mod/`

 -  What: Modlog + scheduled mute/tempban (**ships disabled**)

### welcome — `plugins/welcome/`

 -  What: New-member message + approval/role handling

### counter — `plugins/counter/`

 -  What: Baka button

### fun — `plugins/fun/`

 -  What: Memes (echo/ping/noot/inktober/write)

### misc — `plugins/misc/`

 -  What: Server utilities (banner/welcome/week)
 -  Used by: board (banner)

### roles — `plugins/roles/`

 -  What: Warn-only boot drift check for `roles.manifest`
 -  Read first: manifest core, roles domain

### channels — `plugins/channels/`

 -  What: Warn-only boot drift check for `channels.manifest`
 -  Read first: manifest core, channels domain

### dev — `plugins/dev/`

 -  What: Owner tools + plugin reload/load/unload/enable/disable
 -  Read first: bot


Scheduled tags (`bot.scheduler`)
--------------------------------

 -  `daily` — experience — exp reset: msg counts, cooldowns, lifetime resync.
    Midnight UTC.
 -  `daily.frog` — frogs — capture-count resync. Midnight UTC.
 -  `quarterly` — frogs — season reset (every frog → Basic). First of
    Jan/Apr/Jul/Oct.
 -  `frog` — frogs — per-channel spawn cadence (interval ± fuzz). Per spawn.
 -  `board_weekly` / `board_weekly_close` — board — Sunday scrape → grid +
    poll; close the vote. Sunday 00:00.
 -  `modlog` — mod — mute/tempban expiry (state-backed projection). Per action.
 -  `counter` — counter — baka-button expiry. Per action.
 -  `effect.converge` — effects — external-seam convergence at `expires_at`.
    Per publish.


Key flows
---------

 -  **The grind core:** a message → `experience` awards exp → `levels`/`ranks`
    presenters; configured level/rank messages go through `templates`;
    `exp top` renders via `leaderboard`. `daily` resets the message state at
    midnight.
 -  **The frogs loop:** the scheduler fires `frog` spawns → capture →
    `inventory` +1 → `frog_captured` on `events`; consuming feeds exp back into
    the experience tables via the item definitions; species art resolves
    through `assets`; configured spawn/capture messages through `templates`.
    `quarterly` freezes stacks, `daily.frog` resyncs captures.
 -  **Board weekly:** `board_weekly` scrapes the week, opens a `poll` vote and
    posts grid + banner (`misc`) — Sunday 00:00, re-armed on every fire.
 -  **Effects:** `experience.award_exp` pulls the message-exp multiplier
    (`EffectSeam`); nothing publishes yet — that side is the future badges/shop
    seam. External seams apply on publish and revert via `effect.converge`.
 -  **Manifest drift:** `roles`/`channels` plugins only warn at boot;
    enforcement is manual through `cazzubot-cli`
    (export/diff/check/apply/restore).
 -  **Lifecycle:** unloading a plugin replays its deferred undos in reverse
    (extensions, scheduler tags/rows); durable data is never touched — pending
    work re-arms from state on the next load.
