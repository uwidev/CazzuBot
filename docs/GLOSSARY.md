Glossary
========

The vocabulary of the CazzuBot codebase, stabilized. This is the deep
reference for reading code and talking about features: what each concept
means, where it lives, and how the concepts fit together.

The compact canonical-terms store is `CONTEXT.md` at the repo root — that
file is the single owner of the active vocabulary and should get the
authoritative word on any naming change. This glossary mirrors it in full
and adds the surrounding concepts you meet while diving into the code.

Several names were retired in the 2026-08-31 statuses/outcomes rename and
the follow-up species-compose-behaviors work. Older docs (`docs/FROG.md`,
`docs/needs-rewrite/*`, the `docs/aegis/plans/2026-08-28-*` plans) deliberately
keep the old names; see [Retired vocabulary](#retired-vocabulary) for the
translation table.


The core triad: status · outcome · seam
---------------------------------------

These three terms carry the most history. Read them together before
anything else.

### status

Persistent, scope-aware state applied to a **scope** (one member or the
whole guild): “member X has a contribution from source S on seam K,
effective for target Y until E.” This is a data-model term — it is not a
Discord presence status, a command reply, or a frog’s frozen/normal
**state** (see `FrogState`).

Two halves live in `cazzubot/statuses.py`:

 -  **the statuses seam store** — the persistent machinery: the
    `status_contribution` table plus `publish`/`list`/`fetch`/`clear`/
    `clear_scope` and the fold helpers `product`/`total`. The store is
    deliberately dumb: it records rows, never interprets payloads, never
    computes formulas.
 -  **the status classes registry** — `Status` subclasses plus
    `register_status`/`status_by_source`/`statuses_for_seam`. A status
    class **owns its values** (chance, role ids, duration, reapply
    policy, priority); the store records only the contribution. Feature
    plugins declare their own classes (`plugins/frogs/statuses.py`:
    `POG_REACTION`, `FROGGERS_REACTION`, `CLASSY_ROLE`) and register them.

`Status.key` doubles as the contribution’s `source` — the class IS the
identity (the old `FrogStatus` enum is gone). A feature’s pull maps a
row’s `source` back to its class with `status_by_source` and reads the
values off the class: single source of truth, no payload drift.

Word use: “status” singular = one status effect/class; “statuses” (or
“the statuses”) = the store, the registry, or the mechanism as a whole.

### outcome — retired

“Outcome” is **retired as a concept name**. Its evolution:

1.  Before 2026-08-31, the catch-all was “effects”: a generic store
    (`cazzubot/effects.py`) plus frog-side `Effect` classes.
2.  The 2026-08-31 rename split it: “statuses” (the store) and
    “outcomes” (the frog species-side registry:
    `plugins/frogs/outcomes.py`, `OutcomeKey`,
    `Outcome`/`OutcomePayload`,
    `ExpOutcome`/`ReactionOutcome`/`RoleOutcome`/`ClusterOutcome`).
3.  The species-compose-behaviors work (commits `9ef5696`..`8f2c9da`)
    made status classes own their values, species compose **behaviors**,
    and items compose status classes directly — the outcome registry and
    payload machinery was then **deleted** (`37218fb`).

Today, what consuming an item does is the **item’s own consume glue**
(code); what catching or spawning a frog does is the **species’ composed
behavior**. Items compose statuses (invoked via `bot.statuses`), never
the reverse — that boundary survives.

The word “outcome” still appears in code as plain English (board’s
“Outcome of one weekly run”, the manifest executor’s “Outcome of an
apply”) — those are not concepts.

### seam

A **feature-declared input point on its own calculator** — “message exp”,
“react chance”, “classy role”. The feature that owns the seam holds the
contract: what payloads mean, what the pull computes, and when the
consequence touches the world. The store never interprets seam payloads
and never chooses the formula.

Seams are addressed by a typed `SeamKey` (a Protocol exposing `key` and
`external`) — enum members like `FrogSeam.FROG_REACTION`, never bare
strings in code; strings exist only at the data boundary (the
`status_contribution.seam` column, scheduler payloads). This mirrors the
`InventoryKey` pattern for items.

`external` marks seams whose **consequence touches Discord** (a role
grant). External seams get **convergence**: apply at publish, scheduled
revert at expiry. Internal seams are pure calculator inputs — lazy expiry
only, no jobs, no events. See [Convergence](#convergence--converger) and
the worked examples below.

Current seams:

| Seam                     | Feature    | Fold      | External |
| ------------------------ | ---------- | --------- | -------- |
| `message_exp_multiplier` | experience | product   | no       |
| `frog_reaction`          | frogs      | priority  | no       |
| `classy_role`            | frogs      | converger | yes      |

The word “seam” also has one informal second use: `cazzubot/events.py`
calls the typed event bus “the observation seam between plugins.” Same
metaphor — a shared boundary where flows meet — but a different
mechanism. Seams are persistent calculator inputs; the bus is transient
observation of finished work. Say “seam” unqualified for the status
seam.

### contribution

One `status_contribution` row:
`(scope_kind, scope_id, seam, source, payload, expires_at)`, keyed by
`(scope_kind, scope_id, seam, source)`. “The recipe, not the consequence.” The
store records it; the seam’s pull interprets `payload`.

 -  `expires_at` NULL = permanent. Expiry is **lazy**: a past
    `expires_at` reads as absent and deletes the row on read — no
    sweeper, no scheduler for internal seams.
 -  `clear()`/`clear_scope()` delete rows outright (explicit
    termination). `clear_scope` is timed-only and seam-blind (every seam
    for the target in one DELETE); permanent rows survive.
 -  **publish** records a contribution: module-level `statuses.publish`
    is the pure store write; `bot.statuses.publish` is the engine
    wrapper that also converges external seams and schedules their
    expiry job.
 -  **pull** is the feature reading its seam’s active rows and
    computing whatever it wants: `list`/`fetch` for arbitrary math,
    `product`/`total` for the numeric-seam convention (each payload’s
    `value` key; identity 1.0/0.0 when empty).

### scope

The target of a contribution: `Scope.member(uid)` or `Scope.guild(gid)`.
`kind` + `id` are one unit — build scopes through the classmethods so
they can never disagree. Statuses are scope-aware: the same seam can
serve member modifiers and guild-world modifiers (e.g. a spawn-cadence
multiplier would be a guild scope). A `Status.scope_kind` pins where a
status applies and is enforced at `apply` time.

### convergence / converger

The world-reconciliation rule for **external** seams:

 -  on publish, the consequence applies **immediately** (the converger
    runs synchronously) and a convergence job is scheduled on the
    central scheduler at `expires_at`.
 -  when the job fires, the engine (`Statuses._on_converge_due`, tag
    `status.converge` — `STATUS_CONVERGE_TAG`) re-reads the DB: an
    EXTEND that rolled the row past the fire time re-arms; anything
    else converges.
 -  the converger is **feature code**, registered via
    `bot.statuses.register_converger` at plugin load (internal seams
    are rejected — no world to converge). It reads the seam’s active
    contributions itself, diffs against the member’s actual world
    state, and applies/reverts **idempotently** — a stale job after
    termination is a harmless no-op. Convergence retries ride the
    scheduler’s default retry policy.
 -  explicit `clear`/`clear_scope` of external seams emits
    `StatusesClearedEvent` so subscribers revert the consequence
    instantly instead of waiting for the job.

The shipped example is `RoleConverger` (`plugins/frogs/statuses.py`):
for `classy_role`, it maps each active contribution’s `source` back to
its `RoleStatus`, computes the wanted role id for the current guild
kind, then adds missing / removes only the bound role ids no longer
wanted.

### reapply policy

`ReapplyPolicy` decides what a re-publish of a live
`(scope, seam, source)` does:

 -  **EXTEND** (default) — keep the value, roll `expires_at` forward
    additively (a permanent row stays permanent).
 -  **REPLACE** — overwrite payload and expiry (legacy `set()`
    semantics).
 -  **STACK** — parked: future “stronger” stacking arrives as this
    member.

Because EXTEND is additive, sibling statuses on one seam (Pog/Froggers
reactions) stay separate rows: the stronger one wins while live, and
expiry of the winner falls back to the next automatically.

### provenance

The only payload the store sees from `Status.apply`:
`{"from": <granting item id>}`. Effect values are never baked into
contributions — they live on the status classes and are resolved at
pull time via `status_by_source`. “Provenance” also describes the `from`
field’s role: it records who/what granted the status, not what it does.

### behavior

Code a species or item composes: a plain async callable owning what
happens on an action. Values live on status classes and oracles, not in
payload objects.

 -  species (`plugins/frogs/species.py`, `plugins/frogs/behaviors.py`):
    the `catch` hook (what happens when caught — `grant_catch`: +1 of
    the species’ item + the capture embed; `None` = nothing, explicit)
    and the `spawn` hook (what replaces the catchable frog at spawn —
    `ClusterBurst` for Cluster).
 -  item (`plugins/frogs/items.py`): the `consume` glue — the item’s
    own decision, written as code next to the item.

### effect — retired alias

Retired 2026-08-31 as a concept name; it was a catch-all (visual
effects, cause-and-effect, side effects). Generic-English uses (“side
effects”, “take effect”) are fine. **Deferred effects** in
`cazzubot/lifecycle.py` are a different concept — revertible-effect
undo stacks for plugin unload — not this term; keep them apart when
grepping.


Worked examples
---------------

### Consuming a Pog Frog

1.  The member consumes `frog:pog:normal` (`FrogItems.POG`).
2.  `_consume_item` grants exp from the `frog_exp` oracle, then, for
    each status the item declares (`POG_REACTION`), calls
    `status.apply(bot, scope=Scope.member(uid), provenance=item_id)`.
3.  `apply` checks the scope kind and publishes: seam
    `frog_reaction`, source `frog:blessing:pog` (the status key),
    payload `{"from": "frog:pog:normal"}`, 1-hour duration, EXTEND.
4.  `frog_reaction` is internal — pure store write, no convergence.
5.  Message-time, the reactions listener pulls
    `bot.statuses.list(Scope.member(uid), FrogSeam.FROG_REACTION)`,
    maps each source back via `status_by_source`, and the
    highest-priority live `ReactionStatus` decides the chance —
    Pog’s 1% while live, Froggers’ 7% if both are active.

### Consuming a Classy Frog

`classy_role` is external, so `bot.statuses.publish` runs
`RoleConverger` right away (the role appears on the member) and
schedules a `status.converge` job at the 3-hour expiry. When the job
fires — or the status is explicitly cleared, emitting
`StatusesClearedEvent` — the converger re-reads the DB and removes the
role if nothing wants it anymore.


Items & inventory
-----------------

 -  **Item** — the inventory object dataclass (`cazzubot`): `item_id`
    (immutable oracle), `display_name`, `icon`, `description`,
    `icon_asset`, `consume` glue, `fields`. Declared as bare
    `Item(...)` literals at the enum — no builder/factory indirection.
 -  **item\_id** — the immutable oracle (`frog:pog:normal`): code
    references (enum members) rename freely; stored ids never change.
    Each species × state is a distinct item (normal vs frozen grant
    different exp), so consumption needs no state juggling.
 -  **frog\_exp oracle** — `_SPECIES_EXP` in `plugins/frogs/items.py`:
    the single source for both the consume grant and the info card’s
    “On consumption” field, so display and grant cannot drift.
 -  **item\_statuses** — `_ITEM_STATUSES` maps an `item_id` to the
    status classes the item triggers on consume; the item just names
    them — no outbound payload objects, no registry indirection.
 -  **Consume is item-owned** — the item decides what consuming it
    does; the species is never an inventory item (items live in
    `items.py`, species in `species.py`).


Other core concepts
-------------------

### plugin / extension / loader

The unit of a feature. `Plugin` base (`cazzubot/plugin.py`): `name`,
`extensions` (import paths of lightbulb extension modules, each with a
`loader = lightbulb.Loader()`), `schema`, `scheduled`, `on_load` /
`on_unload`. Plugins are auto-discovered from `plugins/`, one folder per
feature. Loading is two-phase (schemas + extensions first, then
`on_load` hooks) so there are no load-order dependencies; reload-safe.

### service vs controller (CSR boundary)

Service modules (`logic.py`, `factory.py`, `db.py`) never import
discord — enforced by `tests/core/test_csr_boundary.py` (only
carve-out: `plugins/frogs/factory.py`). They take `db`/`settings` +
plain values + injected `now`, and raise `UserInputError` for validation
failures. Extension modules are the controllers: they translate discord
objects ↔ plain values and present. Framework-agnostic member values
travel as `MemberSnapshot`.

### scheduler

One loop over `tasks(tag, run_at, payload)`; tags are registered via
`Plugin.scheduled`; handlers re-schedule by inserting rows; re-armed on
due and on `on_load` (missed-run force checks on boot). The daily/
quarterly wrapper plugins no longer exist — each cadence lives in the
plugin that owns its data. Tags: `daily` (exp resets), `daily.frog` +
`quarterly` (frogs), `frog`, `modlog`, `counter`, `status.converge`.

### settings

Namespaced JSON key-value store (`cazzubot/settings.py`), single guild:
`frog.enabled`, `rank.seasonal.message`, `level.quiet`, … The untyped
JSON carve-out of the db dataclass boundary.

### window

Buffered, level-tagged command reporting to Discord
(`cazzubot/window.py`): `command_window(ctx)` context manager,
`@windowed` decorator, `window_*` one-off helpers. Auto-flushes at end
of command and on error; ephemeral on slash. Distinct from CLI logging
(`logging` stays for bot internals).

### templates

User-configurable message JSON (`cazzubot/templates.py`):
`verify` (jsonschema-validated) → `prepare` → `send` (single
embed/embeds/empty-content, any send target). Placeholders applied via
`utils.deep_map` + per-feature formatters; `allowed_mentions` can only
suppress pings, never broaden them.

### event bus / domain events

Typed bus (`cazzubot/events.py`): plugins `emit` after their
transactional work completes; observers subscribe via `bot.events.on`
and are isolated (failures logged, swallowed). Unsubscribe tokens are
deferred to the lifecycle, so unload withdraws handlers. Frog events:
`FrogCapturedEvent` (capture complete), `FrogConsumedEvent` (consume
complete); no consumers subscribe yet (badges are the planned first).

### guild-scoped listeners

The bot serves **one guild**. Guild-scoped listeners MUST use
`cazzubot.listeners.guild_listener(loader, event_type)` (never bare
`@loader.listener`) — it drops other-guild/DM events before the
handler runs. Scheduler payloads that target channels guard with
`utils.channel_in_guild`.

### UserInputError

The service-layer validation error (`cazzubot.errors`). The lightbulb
error handler in `bot.py` translates it (and
`ConversionFailedException`) into an ephemeral reply — extend the
service, and the command surface learns the error for free.

### database

`Database` (`cazzubot/db.py`): aiosqlite wrapper (WAL, FK on, explicit
`transaction()`). Enums → TEXT, timestamps → ISO-8601 UTC. Reads return
dataclasses via `row_to`/`rows_to` (`fetch_model`/`fetch_models`) —
raw `aiosqlite.Row` never crosses a db-module/public boundary (see
`tests/core/test_db_boundary.py`). No `gid` columns; no FK decorators;
`INSERT OR IGNORE`/`INSERT OR REPLACE` for idempotent writes.
`verify_schema` is the boot-time drift check: the DB schema must match
the Python DDL exactly (extra tables allowed) or boot aborts.

### manifest engine

Shared roles/channels machinery (`cazzubot/manifest/`), driven by the
admin CLI (`cazzubot-cli`): `lines.py` (parser),
`plan.py` (UpdateOp/RenameOp + render blocks), `executor.py`
(ApplyResult, snapshot JSON, backups), `cli.py` (the five verbs —
export/diff/check/apply/restore — behind a `ManifestDomain` spec). The
domain engines (`cazzubot/roles/*`, `cazzubot/channels/*`) hold the
parser specs and apply bodies; `cazzubot/cli/{roles,channels,...}.py`
are thin wiring shells. Manifest files end with a `# vim: ft=txt :`
modeline.

### species / mob

The capturable frog entity (`plugins/frogs/species.py`): `SPECIES` is
the single source of truth (names, rarity, spawn weights, art) — no
catalog table. A species is a mob: its declaration composes its own
behavior as code; capturing grants the item only when the catch
behavior does it. Keys are typed (`FrogItemKey`), never strings, except
at the data boundary.

### FrogState

A frog item’s frozen/normal **state** (`FrogState.NORMAL`/`FROZEN`) —
the seasonal freeze (quarterly cadence) turns frogs frozen; frozen
items grant less exp. Not a status: the word “state” here is the item
variant axis, not the statuses store. When diving in, keep `FrogState`
(an enum of item states) and “status” (the persistent modifier
mechanism) apart.

### oracle

A single source of decision-making values that both the effect path and
the display path read, so they cannot drift: `frog_exp` for exp-per-item,
`_ITEM_STATUSES`/`item_statuses` for what an item triggers. If a value
has a display twin, it should live in an oracle.


Retired vocabulary
------------------

Translation table for old names you will meet in historical docs and
migrations. The left column is gone from live code.

| Old (gone from live code)                                                                                                 | New                                                              |
| ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `cazzubot/effects.py`, `bot.effects`, Effects…                                                                            | `cazzubot/statuses.py`, `bot.statuses`                           |
| `EffectContribution` / `effect_contribution` table                                                                        | `StatusContribution` / `status_contribution`                     |
| `EffectSeam`                                                                                                              | `SeamKey` (typed seam)                                           |
| `EffectsClearedEvent`                                                                                                     | `StatusesClearedEvent`                                           |
| `EFFECTS.md`                                                                                                              | `STATUSES.md` (design spec, docs/needs-rewrite)                  |
| `EffectKey`, `FrogEffect`, `ExpEffect`/`ReactionEffect`/`RoleEffect`/`ClusterEffect`                                      | Status classes (`plugins/frogs/statuses.py`)                     |
| `catch_effect` / `spawn_effect` (species fields)                                                                          | `catch` / `spawn` behavior hooks (`species.py`, `behaviors.py`)  |
| `_SPECIES_CONSUME` / `_SPECIES_OUTCOMES`                                                                                  | item-owned consume glue + `_ITEM_STATUSES` (`items.py`)          |
| outcome library (`OutcomeKey`, `Outcome`/`OutcomePayload`, `ExpOutcome`/`ReactionOutcome`/`RoleOutcome`/`ClusterOutcome`) | deleted — species compose behaviors; items compose statuses      |
| `member_effect` scalar store                                                                                              | statuses seam store (migrations 006 + 007)                       |
| `effect.converge` scheduler tag                                                                                           | `status.converge` (`STATUS_CONVERGE_TAG`)                        |
| “statuses and outcomes” in `docs/FROG.md`                                                                                 | statuses + behaviors + item glue (superseded; kept deliberately) |

Two migration modules do the historical translation:
`scripts/migrations/effect_contributions.py` (old `member_effect` rows →
seam rows) and `scripts/migrations/status_contribution.py`
(`effect_contribution` → `status_contribution`, `effect.converge` →
`status.converge`).


Related docs
------------

 -  `CONTEXT.md` — the compact canonical-term store (single owner of the
    active vocabulary).
 -  `docs/needs-rewrite/STATUSES.md` — the design spec of the
    seam/contribution/pull model.
 -  `docs/needs-rewrite/ITEMS.md`, `docs/needs-rewrite/INVENTORY.md` —
    older item/inventory design records.
 -  `docs/FROG.md` — the older frog spec; uses the retired
    “statuses and outcomes” naming (superseded by status classes +
    behaviors).
 -  `AGENTS.md` — full project rules and architecture overview.
 -  `docs/QUICKSTART.md` + `docs/how-do-i/` — the dive-in walkthroughs.
