Statuses Seam Store
==================

> Status: **design spec** — infrastructure for persistent statuses, planned
> ahead of the frog expansion in `docs/FROG.md`. Infra-only: the four new
> frogs (Pog/Froggers/Classy/Cluster) are a separate follow-up plan that
> consumes this store. Supersedes the `member_effect` data-model section of
> `docs/ROADMAP.md`; complements `docs/ITEMS.md` (consume is item-owned) and
> `docs/FROG.md` (species + statuses requirements).


Why
---

FROG.md's rules section asks for three things the current `member_effect`
store cannot express:

1.  **Reapplying a status extends only the duration, never the intensity.**
2.  **Per-status reapply policy** — “some kind of infrastructure to define
    what happens when you reapply a status that already exists on a user.”
3.  **Generalization beyond member statuses** — statuses might apply to
    things like frog spawn cadence, not just members.

Today `cazzubot/member_effects.py` is one scalar `REAL value` per
`(uid, key)`, replacement-on-set, member-only. It cannot hold a role id, a
react probability + cooldown, or a world-scoped spawn modifier. The four
frogs will need all of those. This design replaces the store with one
generic, scope-aware statuses engine built on a **seam / contribution /
pull** model.


The model
---------

Three concepts, mirroring how game damage formulas separate modifiers from
the calculation:

 -  **Seam** — a feature-declared input point on its own calculator (“message
    exp”, “spawn interval”, “react chance”). The feature owns the seam
    *contract*: which fields/operators it accepts, and — critically — the
    **formula at pull time**. A seam is either **numeric** (arithmetic at
    pull: multiply, sum) or **state** (“any active contribution → do X; none
    → revert X”). A seam whose consequence touches Discord (a role grant) is
    **external** (`external=True`): the engine schedules world-convergence
    for it (see the Reconciliation rule). Numeric seams and per-message pulls
    (react chance — the next message simply stops rolling) are internal: no
    scheduler involvement.
 -  **Contribution** — one recorded fact: “source S published value V into
    seam K, effective for target X until E”. Scoped to a **member** (`uid`)
    or the **guild** (the “world” — spawn cadence lives here); carries a
    **source** (**the status identity** — what published the value; “the
    same status” IS the same source, so several items that publish the same
    status share one identity and the granting item rides in
    the payload as ``"from"`` provenance — see the Phase-1 record below),
    the **payload** (the actual data the seam interprets), and an optional
    `expires_at` (NULL = permanent). The `(scope, seam, source)` key is the
    identity of “the same status”: re-publishing the same source targets
    the same row (`EXTEND`/`REPLACE` act on it), a different source is a
    separate contribution that stacks within the seam. Contributions are
    combinable and individually removable — a pull reads every active row
    on its seam together. A contribution is the **recipe, not the
    consequence**: like an `inventory` row it only *holds* the modifier;
    the seam's pull *interprets* it. It is not history (audit stays in
    feature logs), not an event, and instant handlers (e.g. Cluster's
    spawn) never produce one.
 -  **Pull** — the feature reads its seam's active contributions and computes
    whatever it wants. The store never computes formulas — a future
    order-of-operations formula (additive bucket, then multiplicative, like
    [PoE's damage calculation]) is plain
    feature code at the pull site.

Outcomes with no persistent lifetime (e.g. Cluster's instant spawn) never
touch this store — they stay handler-side, exactly as today.

[PoE's damage calculation]: https://www.poewiki.net/wiki/Damage


Phase-1 record — separation (owner 2026-08-28)
----------------------------------------------

The frog-species plan's Phase 1 (the separation; the four frogs themselves
and their wiring are Phase 2) fixed the ownership model and the
identity rule, recorded here so the code and the store contract agree:

 -  **The ITEM composes statuses (D11, revised 2026-08-31).** What
    consuming an item does is the item's decision, written as code: it
    grants exp (a formula over its own `frog_exp` oracle) and applies the
    **status classes** it names — `plugins/frogs/items.py::_ITEM_STATUSES`
    + the per-item consume glue, beside the oracle. Species carry no
    consume declaration. The old generic outcome-library
    (`plugins/frogs/outcomes.py::OutcomeKey`, payload dataclasses,
    `ExpOutcome`) is **gone**: a status is now a unique class owning its
    own values, invoked via `bot.statuses` + its `apply()`; the item just
    *names* the ones it triggers (no outbound payload objects, no registry
    indirection).
 -  **Identity is the status class, not the item (D3, revised 2026-08-31).**
    The contribution `source` is the status class's `key` — each declared
    status is one `plugins/frogs/statuses.py` class (Pog and Froggers are
    *separate sibling* classes on the same seam, kept as separate rows so
    expiry of the winner falls back to the next). The granting item rides
    in the payload as `"from"` provenance. The **pull folds by priority**:
    a feature's pull maps each row's `source` back to its class via
    `status_by_source` and reads values off the class — never off the row.
    Reapply policy (`EXTEND`/`REPLACE`) is a **per-status** choice on the
    class, not value-merge logic at the publish site.
 -  Frog consumers: `FrogSeam.FROG_REACTION` (internal) and
    `FrogSeam.CLASSY_ROLE` (external, with `RoleConverger`) ship
    **tested but unwired** — no publishers, no converger registration, no
    message listener yet (all Phase 2, by design).


Phase-2 record — the species consume the store (owner 2026-08-28)
-----------------------------------------------------------------

The frog-species plan's Phase 2 (the five FROG.md species) is **implemented
and wired**; the 2026-08-31 statuses compose-behaviors plan then revised
the publisher model. The Phase-1 record above stays true; this adds what
shipped:

 -  **Publishers live as status classes.** Pog/Froggers are sibling
    `ReactionStatus` classes (`plugins/frogs/statuses.py::POG_REACTION`,
    `FROGGERS_REACTION`) and Classy is a `RoleStatus` (`CLASSY_ROLE`) —
    each owns its chance/duration/role ids/priority, and the items that
    trigger them (`_ITEM_STATUSES`) are the only publishers. The plugin's
    `on_load` registers the `RoleConverger` for `CLASSY_ROLE` (so the
    external publish converges synchronously and schedules the expiry job)
    and subscribes `StatusesClearedEvent` for instant role revert;
    `on_unload` withdraws both. Cluster's spawn behavior (`ClusterBurst`)
    is not a contribution at all — instant handlers never touch this store.
 -  **The listener is the consumer.** `plugins/frogs/reactions.py` pulls
    the member's `FROG_REACTION` rows and folds them by priority
    (`_best_reaction`: source → class → highest priority, ties → lowest
    source key), rolls the chance per message with a 10s in-memory
    cooldown, and no-ops while the froggers emoji is unpublished. Sibling
    rows both live; expiry of the winner falls back to the next.
 -  **The class owns the values; the pull reads them off the class.**
    Reapply policy is per-status on the class (reaction statuses EXTEND
    duration-only); there is no value-merge at publish time. The visible
    reaction odds per moment are the same as before in the common cases;
    the difference shows only at expiry-transition edges, which now fall
    back instead of dropping.
 -  **Exp grant is item-owned behavior only** (the `frog_exp` oracle); the
    old `ExpOutcome`/`EXP` outcome fossil is deleted with the rest of the
    outcome library. The POG/FROGGERS/CLASSY oracle rows (30/15, 300/150,
    200/100) live beside the composition, not here.


Schema
------

Replaces the `member_effect` table (core store, boot-run schema like
`inventory`/`settings`):

~~~~ sql
CREATE TABLE IF NOT EXISTS status_contribution (
    scope_kind TEXT NOT NULL,      -- 'member' | 'guild'
    scope_id   INTEGER NOT NULL,   -- uid, or guild id
    seam       TEXT NOT NULL,      -- derived from a typed SeamKey
    source     TEXT NOT NULL,      -- what published this (e.g. a frog item_id)
    payload    TEXT NOT NULL,      -- JSON blob; interpreted only by the seam's pull
    expires_at TEXT,               -- NULL = permanent; lazy expiry + prune on read
    PRIMARY KEY (scope_kind, scope_id, seam, source)
)
~~~~

 -  **Typed keys, never strings**: `SeamKey` is a Protocol exposing `.key`
    (the derived storage string) plus the seam's `external` flag, exactly
    like `InventoryKey` in `cazzubot/inventory.py`. Features declare their
    seam enums; the store only ever sees derived strings. The core ships
    **zero seams** — experience declares `message_exp_multiplier`; frogs
    declare `react_buff`/`spawn_interval` in their own plans.
 -  **Payload**: JSON via `db.dump_json`/`load_json`, typed at the feature
    boundary with payload dataclasses (e.g. `{"op": "mult", "value": 2.0}`,
    `{"role_id": "…"}`, `{"chance": 0.07, "cooldown": 10}`). The store never
    interprets payloads.
 -  **Lazy data expiry** (deliberate, not a shortcut): a past `expires_at`
    reads as absent and prunes the row — no timer, no sweeper, no scheduler.
    The row *is* the truth for its own question, so it can never be stale;
    an eager sweeper would add scheduled work without removing the read-time
    check (a row can pass its expiry between any two reads, whoever deletes
    it). This laziness is **data-side only** — world-side consequences are a
    separate mechanism (Reconciliation rule below).


API — `cazzubot/statuses.py`, service `bot.statuses`
--------------------------------------------------

Replaces `MemberEffects`; same module shape as `inventory.py` (module-level
functions taking `db` + a `CazzuBot`-bound service class owning the schema).
No hikari imports — `bot` is a TYPE\_CHECKING parameter (CSR boundary stays
green).

~~~~ python
# Scope: typed, kind + id cannot mismatch
Scope.member(uid)    # scope_kind='member'
Scope.guild(gid)     # scope_kind='guild'

async def publish(db, scope, seam: SeamKey, source: str, payload,
                  *, duration, policy=ReapplyPolicy.EXTEND) -> None
async def list(db, scope, seam: SeamKey) -> list[StatusContribution]  # prunes expired
async def fetch(db, scope, seam: SeamKey, source: str) -> StatusContribution | None
async def clear(db, scope, seam: SeamKey, source: str) -> None          # delete one contribution
async def clear_scope(db, scope) -> None                                # delete a whole scope (timed only)
async def product(db, scope, seam) -> float   # numeric convenience: multiply all values, 1.0 when empty
async def total(db, scope, seam) -> float     # numeric convenience: sum, 0 when empty
~~~~

 -  Numeric conveniences never choose *order* — a pull with a complex formula
    ignores them and does its own math.
 -  Row shape crosses the API as the `StatusContribution` dataclass via
    `fetch_model` (model-boundary rule); the payload stays a JSON dict field.


Reapply machinery
-----------------

 -  “The same status” = `(scope, seam, source)`.
 -  `ReapplyPolicy`, chosen **at publish time** by the publisher, applied in
    exactly one place inside `publish`:

| Policy             | Behavior on re-publish while live                                                                          | Where                               |
| ------------------ | ---------------------------------------------------------------------------------------------------------- | ----------------------------------- |
| `EXTEND` (default) | keep value, **additively roll `expires_at` forward** by the new duration (1h + 1h = 2h from first publish) | the doc's rule                      |
| `REPLACE`          | overwrite payload + `expires_at = now + duration`                                                          | preserves today's `set()` semantics |
| `STACK`            | **parked, unimplemented** — future “stronger” stacking arrives as one enum member                          | the doc's “possibly later”          |

 -  If the existing row is already expired at publish time, it is pruned and a
    fresh row is written (`now + duration`).


Reconciliation rule — world vs data laziness
--------------------------------------------

Two copies of every *external* status exist: the **contribution row**
(the recipe) and a **real-world consequence** (a granted role). Expiry
or clearing removes the recipe; the consequence must be **converged** —
the DB is authoritative and Discord is re-made to match. Internal
statuses (exp multipliers, react chance) have no stored consequence: they stop being read
and nothing else happens.

1.  **The seam contract declares externality** — a seam whose consequence
    touches Discord carries `external=True`; internal seams schedule
    nothing. The engine tracks external seams structurally, so “keeping
    track of everything that needs syncing” is never ad-hoc.
2.  **Apply immediately, revert on schedule** — publishing an external
    contribution applies the consequence at once (one API call), then
    schedules a **convergence job on the central scheduler** at
    `expires_at` (re-armed on boot like every other tag, missed runs
    force-checked; rate-paced per the existing roles/assets pacing
    patterns). The job reads the DB, computes the desired state, diffs
    against the member's *actual* state, and applies — **idempotent and
    re-runnable**, so interleavings and missed runs cannot corrupt state.
    Discord has no transactions, so convergence is eventually consistent by
    nature; the goal is “as soon as possible within rate limits”, never
    “whenever someone happens to notice”.
3.  **Two-way pulls stay as the safety net** — a pull still treats “no
    active contributions” as a real state (active → apply, inactive →
    revert), but this is no longer *the* mechanism.
4.  **`StatusesClearedEvent`** on `bot.events` — emitted by the caller after
    any explicit removal that touches external seams (`clear` or
    `clear_scope`), so termination reverts *instantly* rather than waiting
    for the scheduled job.

The store stays dumb; convergence logic is feature code invoked by the
scheduler (expiry path) or the event (cleanse path).

### Termination — delete, never expire-at-now

Immediate termination (`clear` of one contribution, `clear_scope` of a
whole target) **deletes the rows**; it never sets `expires_at = now`. A
spoofed expiry would leave corpse rows until a read prunes them, would not
move the external convergence job (that lives in the scheduler, keyed by
when it was scheduled, not by table contents), and would muddy the
distinction between “the buff ran out” (expiry — converges the consequence
only) and “an owner action killed it” (clear — also resets pull-side state
such as cooldowns). That distinction travels through the **caller paths**
(the event says cleared, the scheduler says expiry), never through the
rows — no tombstones.

External termination has two backstops: the already-scheduled convergence
job fires whenever it fires and converges **idempotently** (no active
contribution → revert; already reverted → no-op), and the emitted
`StatusesClearedEvent` makes the revert instant. Convergence jobs
**re-evaluate on fire**: if an `EXTEND` rolled the row past the fire time
they see it active and re-arm; otherwise they revert. Jobs never need
cancellation — a stale one is redundant, never wrong.

**Cleanse semantics** (user decisions, 2026-08): `clear_scope` removes
timed contributions only (`expires_at IS NOT NULL` — permanent rows
survive), is cross-feature (every seam for the target, one seam-blind
`DELETE`), and reverts instantly via the event. The *cleanse item itself*
(definition, consume glue, registration) is deliberately out of scope — the
mechanism is proven by integration tests with a fake external seam.


Relationship to the scheduler
-----------------------------

`status_contribution` deliberately coexists with `bot.scheduler`'s
`tasks`
table — the store holds **state**, the scheduler holds **work**:

 -  A contribution is a **fact** (“X is in effect until T”), read by pulls
    until it dies; a task is a **command** (“at T, run handler X once”),
    executed by the loop and consumed (“due, handled, gone”).
 -  The store is **pulled** (passive, lazy reads); the scheduler **pushes**
    (polls due rows and dispatches).
 -  Game state is *never* derived from the tasks table — “is this status
    active?” is answered only by contributions; tasks are a queue, not
    truth.
 -  The crossing is one-way: **external statuses translate their expiry
    into scheduled work** (the convergence job), and task handlers may
    publish or clear contributions as side effects of their work. The
    scheduler never reads the status table; a contribution is never
    implemented as a task.


Migration
---------

 -  `member_effect` table + `MemberEffects` service retire; `EXP_MULTIPLIER`
    becomes a contribution to experience's `message_exp_multiplier` seam.
 -  `experience.logic.award_exp` switches from `member_effects.get(...)` to
    `statuses.product(scope=Scope.member(uid), seam=…)` (1.0 when absent
    — same math).
 -  Migration script through the `scripts/migrate.py` harness (dry-run by
    default, backup before write; see `docs/add-a-migration.md`): create
    `effect_contribution`, fold any `member_effect` rows (uid → member scope,
    key → seam key, `value` → `{"op": "mult", "value": v}` payload), drop the
    old table; the 2026-08-31 rename (migration 007) then renames the table
    to `status_contribution` (and the converge tag to `status.converge`).
    Run while the bot is stopped — the boot `verify_schema` guard
    refuses the legacy shape until then. (Live `member_effect` rows are ~zero
    today: `EXP_MULTIPLIER` is only set in tests.)


Testing
-------

 -  Unit (`tests/core/test_statuses.py`): EXTEND additive roll (two publishes
    → one row, value unchanged, `expires_at` = first + 2×duration); REPLACE
    overwrite; expiry-at-publish prunes then writes fresh; lazy data expiry
    (read → absent, prune); scope isolation (member A ≠ member B ≠ guild);
    `product`/`total` on empty (1.0 / 0); JSON payload round-trip;
    `clear`/`clear_scope` delete rows (never expire-mark); `clear_scope`
    leaves other scopes and permanent rows.
 -  Integration: a fake **external** seam's publish applies its consequence
    and schedules a convergence job at `expires_at`; the job reverts
    idempotently (double-run → single revert); an internal seam schedules
    nothing; a fake state seam reverts synchronously on
    `StatusesClearedEvent`.
 -  Existing `tests/core/test_member_effects.py` re-expressed through the new
    store; `award_exp` behavior preserved (tests stay green through the new
    path).
 -  CSR + db-boundary sweeps stay green.


Non-goals (this plan)
---------------------

 -  The frog outcomes themselves and the four new frogs (separate
    follow-up plan).
 -  World-scope consumers — the `spawn_interval` seam (frogs plan).
 -  React cooldown state — pull-side/feature-side state, not a contribution.
 -  Cluster's instant spawn — handler-side, never stored.
 -  `STACK` implementation.
 -  Any core-shipped seams.
 -  The cleanse item definition.


Acceptance
----------

 -  Two `publish` calls with `EXTEND` → one row, value unchanged, expiry
    additively extended.
 -  `REPLACE` re-publish → payload + expiry overwritten.
 -  Expired rows read as absent and are pruned (data-side lazy).
 -  External seams: publish applies the consequence and schedules a
    convergence job at `expires_at`; the job is idempotent (double-run
    harmless); internal seams never schedule.
 -  `clear_scope` deletes timed contributions for one target only; the fake
    seam reverts its consequence synchronously on `StatusesClearedEvent`.
 -  Termination deletes rows (no tombstone); external terminate emits
    `StatusesClearedEvent`; a stale convergence job after termination is a
    no-op.
 -  `award_exp` behavior unchanged (multiplier via the seam).
 -  Migration dry-run + apply on the dev DB; boot passes `verify_schema`.
 -  Full suite green, `ruff check` clean.


Naming note
-----------

`cazzubot/statuses.py` is the single statuses module: the **persistent
status store** (seam/contribution/pull) AND the **status classes
registry** (`Status` + `register_status`/`status_by_source`) — a status
class owns its values; the store records the contribution; a feature's
pull maps a row's `source` back to its class. Feature plugins declare
their own `Status` subclasses (`plugins/frogs/statuses.py`) and species
compose behaviors (`plugins/frogs/behaviors.py`). The old
`plugins/frogs/outcomes.py` outcome library is retired; neither “outcome”
nor the generic catch-all “effect” is a concept anymore (see
`docs/CONTEXT.md`).


References
----------

 -  `docs/FROG.md` — the rules section (3 asks) + the frog outcomes that
    will consume this store
 -  `docs/ROADMAP.md` — the effects-registry section and the `member_effect`
    data model this supersedes
 -  `docs/ITEMS.md` — item-owned consume; where a future cleanse item's glue
    would live
 -  `cazzubot/inventory.py` — the `InventoryKey` pattern `SeamKey` mirrors
 -  `docs/add-a-migration.md`, `docs/PLAN_DB_MODELS.md`, `docs/TESTING.md`
