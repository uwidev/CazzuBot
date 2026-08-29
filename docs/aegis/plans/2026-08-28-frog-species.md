Frog Species — FROG.md Implementation Plan
==========================================

> Date: 2026-08-28 · Status: **Implemented** — Phases 1 + 2 (tasks 1, 3–9)
> closed; suite green at 706. · Owner: CazzuBot
> Spec: `docs/FROG.md` · Supersedes nothing; extends the expansion roadmap
> (`docs/needs-rewrite/ROADMAP.md`, Phases 0–4 done, ship = exp only).
>
> **Phase split (owner 2026-08-28; updated 2026-08-29):** Phase 1 — the
> items / frog / effects **separation** — was executed from the handoff
> (`docs/aegis/plans/2026-08-28-frog-species-handoff.md`) and is **closed**:
> typed seams, the reaction/role modifiers, `RoleConverger`, and the
> item-owned consume composition pipeline ship tested (suite 693 green).
> **Phase 2 — the species implementation — is now closed: tasks 1, 3–9
> were executed from the handoff (the boot sheet); the five FROG.md
> species, their wiring, and the driver e2e ship at suite 706.**


Goal
----

Implement the five frog species exactly as specified in `docs/FROG.md`,
reusing the existing species/effect/inventory/effects infrastructure:

| Species  | Spawn weight | Capture / consume behavior (per FROG.md)                                                                                                    |
| -------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Basic    | 1000         | +1 Basic; consume → 10 exp                                                                                                                  |
| Pog      | 200          | +1 Pog; consume → 30 exp + 1h, 1% chance bot reacts 🐸-froggers, 10s cd                                                                     |
| Froggers | 50           | +1 Froggers; consume → 300 exp + 1h, 7% chance bot reacts froggers, 10s cd                                                                  |
| Classy   | 200          | +1 Classy; consume → 200 exp (placeholder) + a role for 3h (dev 1542294599358353430 / prod 1542293782588952696)                             |
| Cluster  | 300          | **Uncatchable.** On spawn, burst 4–10 Basic Frogs into text channels within ±2 of the spawn channel, delayed to avoid rate limits. No item. |

FROG.md's reapplication rule — *consuming more of the same item while its
effect is live only extends the duration, never strengthens it* — is
already satisfied by `cazzubot/effects.py` `ReapplyPolicy.EXTEND` (a
re-publish of the same `(scope, seam, source)` rolls `expires_at`
forward, keeping the value). The “generalize stacking to any effect”
bullet (e.g. a world-side spawn-interval effect) is also already
supported by the engine (`Scope.guild` seams); it is deliberately **out
of scope** here — FROG.md's current species list does not need it.


Architecture
------------

Behavioral flow per species:

 -  **Capture** (`plugins/frogs/factory.py` `FrogCatchMenu.catch`):
    catch → `member_frog_log` + lifetime counter → `catch_effect` (all new
    species have none) → default grant is +1 inventory (basic path).
    Cluster never reaches a catch button: `spawn_and_wait` detects its
    `spawn_effect` and runs the explosion instead of posting a frog.
 -  **Consume** (`/inventory consume` → `Item.consume` glue in
    `plugins/frogs/items.py`): the ITEM composes what consuming does —
    glue grants exp from the `frog_exp` oracle (item-owned values), then
    runs the item's composed effect applications (the `EffectKey`
    modifiers, e.g. reaction chance, role grant) with the member scope,
    then emits `FrogConsumedEvent`. The species declares NO consume
    behavior — catch/spawn are the only entity hooks.
 -  **Spawn** (`factory.spawn_and_wait`): species is rolled by weight; a
    species with a `spawn_effect` (Cluster) short-circuits before any
    message: `ClusterEffect.spawn` finds the text-channel blast zone
    (±`radius` by position), rolls 4–10 targets, and starts each child
    Basic-frog spawn (`factory.spawn_and_wait`, forced species BASIC) as a
    tracked background task, staggered by `delay` seconds.

**Ownership — the item composes, effects modify** (owner 2026-08-28):

 -  **Item = composition root.** What consuming an item does is decided by
    the item: it grants exp (a formula over its own `frog_exp` oracle) and
    composes the state-modifying effects it applies (timed reaction
    chance, role grant, …). Composition data lives beside the oracle in
    `plugins/frogs/items.py` (`_SPECIES_CONSUME` — the effect payloads an
    item applies); species carry no consume declaration.
 -  **Effect = generic, composable state modifier.** The `EffectKey`
    registry in `plugins/frogs/effects.py` is a *library of primitives*:
    each modifier takes a **Scope** (member or guild) so any caller can
    apply it to any target — item glue today (member scope), a future
    admin `/effect apply` command tomorrow (any member/guild). Modifiers
    never decide *what happens*; callers compose them.
 -  **Store = persistence** (`cazzubot/effects.py`): seams/contributions,
    identity by effect, EXTEND/REPLACE, converge, lazy expiry — unchanged.

**Effect identity — the item is not the effect**: the engine's
`(scope, seam, source)` key already *is* “the same effect”, so identity is
decided by what we pass as `source`. Pog and Froggers are the SAME effect
(reaction chance): both publish under the shared effect identity
`FrogEffect.REACTION` — never per-item sources — and the granting item
rides in the payload as `"from"` provenance. Strongest value wins while
active (a Froggers overwrites a live Pog's 1% → 7%); a weaker consume keeps
the value; every consume extends the window additively. The value merge is
feature-side (the store never interprets payloads). No engine/schema change
and no migration are needed for this.

New vs existing surfaces: `FrogSeam` (seam enum, mirrors experience's
`EffectSeam`) + `FrogEffect` (effect-identity enum),
`ReactionEffect`/`RoleEffect`/`ClusterEffect` + payloads (new `EffectKey`
members), `RoleConverger`, `reactions.py` listener,
`Species.spawn_effect` field, item-owned consume composition
(`_SPECIES_CONSUME`), six new `FrogItems` members + exp-oracle rows.
Nothing new in the core.


Tech Stack
----------

Python 3.14, hikari 2.5, hikari-lightbulb 3.2, aiosqlite, pendulum, uv.
Tests: pytest, `tests/driver.py` (`run_slash`/`press_button`/`submit_modal`),
typed fakes in `tests/fakes.py` (no hikari in tests infra).


Baseline/Authority Refs
-----------------------

 -  Required baseline refs: `docs/FROG.md` (spec),
    `docs/needs-rewrite/ROADMAP.md` (expansion roadmap + conventions),
    `docs/aegis/baseline/2026-08-28-frog-species-baseline.md` (measured
    state), `AGENTS.md` (project conventions).
 -  Acknowledged before planning: `docs/FROG.md`, ROADMAP,
    `plugins/frogs/{species,effects,items,factory,db,extension,events, __init__}.py`,
    `cazzubot/{effects,inventory,assets,listeners, config,events,models}.py`,
    `plugins/inventory/extension.py`, `plugins/experience/logic.py` (EffectSeam
    precedent), `tests/{fakes.py,core/test_csr_boundary.py}`.
 -  Cited in plan: all of the above.
 -  Missing refs: none blocking.
 -  Decision: continue.


Requirement Ready Check
-----------------------

 -  Requirement source refs: `docs/FROG.md` (frog types + rules).
 -  Goals and scope refs: ROADMAP (Phases 0–4, item-vs-entity split,
    “no catalog table”, EffectKey registry convention).
 -  User / scenario refs: species list + weights + effects in FROG.md.
 -  Acceptance / verification: per-species behavior tests + driver
    end-to-end (below).
 -  Open blocker questions: **none blocking** — four tunable decisions with
    defaults (see Decisions); each is a one-line code edit and matches the
    ROADMAP's own “defaults until the owner tunes them” stance.
 -  Decision: **ready**.


Change Necessity
----------------

 -  User-visible need: five frog species with distinct consume/spawn
    behaviors from FROG.md.
 -  No-change / non-code option: not possible — species and effects are
    code by design (no catalog table; tuning = editing `species.py`).
 -  Why code change is necessary: the behavior does not exist yet
    (reaction chance, role grant, cluster explosion); modest infra is
    missing only at the species level (consume-effect dispatch, spawn-side
    hook, two seams + a listener + a converger).
 -  Minimum change boundary: `plugins/frogs/` (+ one consumer tweak in
    `cazzubot/models.py` for the new enum members, + `tests/fakes.py` for
    the cluster test channel list).
 -  Decision: **code-change**.


Existence Check
---------------

 -  Proposed new surface: `FrogSeam` enum, `ReactionEffect`/
    `RoleEffect`/`ClusterEffect` + payloads, `RoleConverger`,
    `plugins/frogs/reactions.py`,
    `Species.spawn_effect` field, the item-owned `_SPECIES_CONSUME`
    composition, 6 new `FrogItems`.
 -  Existing owner / reuse candidate: the effects engine
    (`cazzubot/effects.py` — seams, EXTEND, external converge jobs), the
    species-effect registry (`EffectKey`), the item oracle pattern, the
    `guild_listener` helper, `utils.schedule_delete` background-task
    precedent.
 -  Why existing surface is insufficient: each is a *behavioral* gap — no
    seam for reaction chance, no external seam/converger for a role grant,
    no spawn-side hook, no message-time listener.
 -  Creation proof: each new file fills exactly one role (seams = typed
    keys only; reactions = listener). The cluster spawn hook lives in the
    service-named `effects.py` with its factory dependency injected as
    `spawn_impl` (the CSR boundary forbids hikari AND the import graph
    forbids a reverse `effects → factory` edge — see Task 5).
 -  Entropy / retirement impact: seams/effects are enum members (the
    registry convention); listener/cluster follow existing module shapes.
    Retirement trigger: a species removed = drop its registry entry + items
    (no table changes).
 -  Decision: **add-with-proof** (proof = task-level acceptance below).


Architecture Integrity Lens
---------------------------

 -  Invariant: the effects engine is the single owner of reapplication
    semantics (EXTEND) and external world-convergence; frog code only
    defines seams, publishes, and pulls. No parallel “timed effect” store.
 -  Canonical owner / contract: `bot.effects` (timed + external),
    `bot.inventory` (holdings), species registry (entities), `FrogItems`
    (items + consume glue).
 -  Responsibility overlap: none — exp stays item-owned (oracle), timed
    effects stay in the effects engine, the reaction listener only reads
    the seam.
 -  Higher-level simplification: the ROADMAP's planned `CLUSTER =`
    `ClusterEffect()` hint becomes real as a `spawn` hook, not a catch
    hook.
 -  Verdict: pass.


Plan Pressure Test
------------------

 -  Owner / contract / retirement: all behavior lands inside the frogs
    plugin; core untouched except 4 enum members.
 -  Architecture integrity: routed through existing engine (see Lens).
 -  Verification scope: unit + CSR + boundary + driver tests, exact
    commands per task.
 -  Task executability: tasks are small, file-scoped, sequential (shared
    files), each with complete code.
 -  Pressure result: **proceed**.


Plan-Time Complexity Check
--------------------------

 -  Target files: `plugins/frogs/species.py` (+4 species, +2 fields),
    `effects.py` (+3 effect classes + 3 payloads + converger + cluster
    spawn hook + helper), `items.py` (+6 items + oracle rows + dispatch),
    `factory.py` (+spawn dispatch + 2 guards), `extension.py` (catalog
    branch), `models.py` (+4 keys), `tests/*` (+coverage), plus 1 new
    module (`reactions.py`).
 -  Current pressure: low — effects.py 168 lines, items.py 146, species.py
    83, factory.py 433 (controller, carve-out).
 -  Projected post-change pressure: low-moderate; effects.py grows to
    ~330 (the cluster spawn hook is ~120 lines), others stay < 400 except
    factory (gains ~25).
 -  Owner fit: all changes belong to the frogs plugin (self-contained).
 -  Add-in-place risk: acceptable — effects.py grows by two effect classes
     -  the cluster hook, but each is one cohesive block; the single new
        module (`reactions.py`) keeps the reaction listener out of
        service-named files.
 -  Better file boundary: new `reactions.py` (CSR-safe listener home);
    the cluster spawn hook stays in `effects.py` (registry home) with an
    injected `spawn_impl`.
 -  Recommendation: **edit-in-place + one new module file**.


TDD Route
---------

~~~~ text
TDD Route:
- Mode: auto
- Decision: strict
- Strict authority: recorded auto decision (behavior + contract +
  producer/consumer + persistence-adjacent signals apply throughout)
- Strict signals: reaction roll behavior, role converge/revert, cluster
  explosion, EXTEND seam semantics via the real engine, listener
  producer/consumer
- Light eligibility: not eligible (behavior change + shared consumer)
- TDD-fit exception: mechanical registry/item additions get direct
  implementation + regression verification instead of RED cycles
- Test posture: RED test first for behavioral slices; regression tests
  for mechanical slices
- Reason: the effects engine and the capture/consume pipelines are
  shared, contract-bearing owners; behavior must be pinned by tests
- Verification: uv run pytest per task (exact commands below); suite +
  ruff + basedpyright at the end
~~~~

Each behavioral task below follows **write failing test → verify RED →
minimal change → verify GREEN**. Mechanical tasks (registry rows, item
literals) make the change then add regression tests.


Decisions (owner-tunable, non-blocking)
---------------------------------------

| #   | Decision                                            | Default in plan                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Classy consume exp “X”                              | **200** (owner-set 2026-08-28, `_SPECIES_EXP[CLASSY][NORMAL]`; still a placeholder)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| D2  | Frozen-state exp for new species                    | **half of normal** (Pog 15, Froggers 150, Classy 100); Basic keeps legacy 3 — one-line edits. Non-basic frozen stacks are legacy-only after the season-reset rule (D10): frozen items stay consumable, but the quarterly reset no longer produces them                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| D3  | Reaction identity (the “item vs effect” separation) | **identity = the effect, not the item** (owner 2026-08-28): Pog and Froggers are ONE effect — both publish to the single `(member, seam, source)` row under the shared effect identity `FrogEffect.REACTION`; the granting item is provenance (`payload["from"]`). While active: **strongest chance wins** (a Froggers overwrites a live Pog's 1% → 7%; a weaker consume never downgrades) and **every consume extends the window additively** (old `expires_at` plus its hour — the “duration only” spirit); after expiry, a fresh consume starts anew. The merge is feature-side in `ReactionEffect.consume` (fetch → compare → EXTEND, or REPLACE with remaining+duration); the listener reads the single row — no read-time fold. Engine untouched: `(scope, seam, source)` already means “the same effect”; we feed it effect ids, not item ids |
| D4  | Reaction cooldown store                             | **in-memory dict** on `reactions.py` (restart at worst allows one extra react; no table needed)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| D5  | Reaction emoji                                      | `FrogAsset.FROG_FROGGERS` (FROG.md: “react… with the froggers emoji” — the species' own emoji asset); listener no-ops while unpublished                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| D6  | Cluster blast zone                                  | guild text channels sorted by `(position, id)`; zone = spawn index ±2 (radius), clamped; N = uniform 4..10 targets with replacement; child spawns are tracked background tasks staggered `delay = 0.75s` (rate-limit guard), child `persist` = the parent spawn's persist                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| D7  | Cluster art / item                                  | `Species.art` becomes `FrogAsset \| None` (cluster = None, “Asset: placeholder” per doc); no cluster item — uncatchable                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| D8  | Frozen items' art                                   | new species' frozen items reuse the normal-species art (Basic Frozen keeps its own `FROG_BASIC_FROZEN`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| D9  | Rarity strings                                      | basic `common`, pog `uncommon`, froggers `rare`, classy `rare`, cluster `special` (cosmetic only)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| D10 | Season end (quarterly reset)                        | **every frog becomes a Basic Frog** (“use it or lose it”, owner 2026-08-28): non-basic stacks (normal AND frozen) fold into `frog:basic:normal`, then Basic's own normal→frozen devaluation runs — after a reset you hold `frog:basic:frozen` (3 exp). Frozen state stays (basic + legacy non-basic rows) — Task 6                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| D11 | Consume composition ownership                       | **the ITEM composes, effects modify** (owner 2026-08-28): what consuming an item does is decided by the item — exp (its `frog_exp` oracle) plus its composed effect applications (`_SPECIES_CONSUME` in `items.py`); species carry no consume declaration. Effects are generic, scope-aware state modifiers (the `EffectKey` primitives take a `Scope`), callable from any entry point: item glue today, a future admin `/effect apply` for any member/guild. Exp is item behavior, not a modifier — `ExpEffect`/`EXP` stays in the codebase but unused, slated for removal (Task 9 note)                                                                                                                                                                                                                                                            |


File Map
--------

**Create:**

 -  `docs/aegis/plans/2026-08-28-frog-species.md` (this plan)
 -  `plugins/frogs/seams.py` — `FrogSeam` (SeamKey pattern) + `FrogEffect`
    (effect identities — the contribution `source`)
 -  `plugins/frogs/reactions.py` — guild-scoped message listener + `loader`

(`ClusterEffect`/`ClusterPayload` live in `plugins/frogs/effects.py`, not
a new module, because `effects.py` is the registry home and the spawn
implementation is injected via `spawn_impl` to keep the import graph
acyclic — see Task 5.)

**Modify:**

 -  `cazzubot/models.py` — `FrogItemKey` += POG/FROGGERS/CLASSY/CLUSTER
 -  `plugins/frogs/species.py` — `Species` += `spawn_effect`, art optional
    (no consume declaration — the item composes); `SPECIES` = 5 entries
    with FROG.md weights
 -  `plugins/frogs/effects.py` — `ReactionEffect`/`RoleEffect`/`RolePayload`
    /`ReactionPayload`/`ClusterEffect`/`ClusterPayload` (spawn hook delivered
    via injected `spawn_impl`), `RoleConverger`,
    `EffectKey` += REACTION/ROLE/CLUSTER, `frog_item_key` helper
 -  `plugins/frogs/items.py` — exp-oracle rows + item-owned composition
    `_SPECIES_CONSUME` + `classy_role_ids()`, `_consume_item` runs the
    composition, 6 new item members + glue, `_consume_blurb`
 -  `plugins/frogs/factory.py` — spawn-effect short-circuit in
    `spawn_and_wait`, uncatchable guard in `FrogCatchMenu.catch`, art-None
    guards in `_frog_content` / capture embed
 -  `plugins/frogs/extension.py` — catalog branch for spawn-effect species +
    new-species display; reactions extension registered
 -  `plugins/frogs/db.py` — `freeze_frogs` → `season_reset_frogs` (every
    frog → Basic at the quarterly rollover, “use it or lose it”)
 -  `plugins/frogs/__init__.py` — register converger + `EffectsClearedEvent`
    subscription + unsubscribe on unload; `ClusterEffect.spawn_impl`
    injection; `extensions` += reactions; the `quarterly` handler calls
    `season_reset_frogs`
 -  `plugins/frogs/assets.py` — `FROG_POG`/`FROG_FROGGERS`/`FROG_CLASSY`
    (EMOJI kind, placeholder PNGs, per ROADMAP “placeholder first”)
 -  `tests/fakes.py` — `FakeRest.fetch_guild_channels` (cluster zone)
 -  tests: `tests/plugins/frogs/test_species.py`, `test_effects.py`,
    `test_db.py`, `test_extension.py`, `test_cadences.py` (+ new
    `test_reactions.py`, `test_cluster.py`, `test_items.py`),
    `tests/integration/test_frog_driver.py`
 -  Docs: `docs/PLUGINS.md`, `docs/SYSTEMS.md`,
    `docs/needs-rewrite/ROADMAP.md` (status + new phases),
    `docs/FROG.md` (nothing — it is the spec)

**Unchanged:** `cazzubot/{effects,inventory,assets,listeners,config}.py`,
scheduler, all other plugins, DB schema (no migration).


Compatibility Boundary
----------------------

 -  **No schema change, no migration**: species are code; new items are new
    `inventory` rows only; `member_frog_log.type` stores new keys (TEXT).
 -  Existing commands/flows unchanged: `/frog profile`/`catalog`/
    `register`/`spawn`/`fake`, `/inventory consume`. The quarterly tag
    keeps its cadence and arming but its fold becomes the season reset
    (every frog → Basic, Task 6); the daily resync, boot sweeping of
    `frog:catch:*` messages and `frog_messages` cleanup are untouched.
 -  Item definitions remain bare `Item(...)` literals; exp values stay in
    the `frog_exp` oracle; info card and catalog read the same oracle +
    species payloads (display and grant cannot drift).
 -  **Identity is the effect, not the item** (owner 2026-08-28): several
    items that ARE the same effect publish under one shared effect
    identity (`FrogEffect.REACTION`/`CLASSY_ROLE`), the granting item
    rides in the payload as provenance; no engine/schema change — the
    `(scope, seam, source)` key already means “the same effect”.
 -  CSR boundary holds: `species.py`/`effects.py`/`db.py` stay hikari-free
    (effects.py gains the cluster spawn hook with its hikari-free channel
    check and an injected `spawn_impl`); hikari lives in the new
    non-service module (`reactions.py`) and in `factory.py` (existing
    carve-out).
 -  Every new listener registers via `cazzubot.listeners.guild_listener`.
 -  Timed effects enforce EXTEND through `bot.effects`; the reaction seam
    is internal (lazy expiry), the role seam external (converger + converge
    job + `EffectsClearedEvent` revert).
 -  Weights change (Basic 1.0 → 1000.0): intended per FROG.md; the weighted
    roll distribution shifts (Basic ≈ 57% of spawns).
 -  Cluster cannot be caught: spawn short-circuit + defensive un-catchable
    guard; no `frog:cluster:*` item exists, so it cannot be consumed.
 -  Worker tasks must not block the scheduler: cluster child spawns are
    background tasks (precedent `utils.schedule_delete`).


Risks
-----

 -  **Role converge on members who left the guild** — `fetch_member`
    raises; converger catches, logs, returns; the scheduled job retries
    (infinite backoff), converging the row away once expired (the retry
    with the same payload re-runs; a NotFound member converges nothing).
 -  **Reaction rate limits** — 10s per-user throttle + NotFound/RateLimit
    swallowing; worst case a missed chance, never a crash.
 -  **Cluster bursts spamming channels** — delay stagger + bounded count
    (4–10); children are normal catchable frogs with the channel's persist.
 -  **Redundant converge jobs on EXTEND** — engine contract: “a redundant
    one is never wrong”; converger is idempotent.
 -  **Deploy order** — run the *existing* `scripts/migrate_frog_species.py`
    (species-model migration, still pending on live dev/prod) while the bot
    is stopped BEFORE live-testing this branch on a legacy-shaped DB;
    `push_to_prod.sh` clobbers `data/` (remember the runbook landmine).
 -  Rollback: revert the commit; registry/items are code — no data
    migration needed (new item rows are additive).

   - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

Tasks
=====

> Every command runs from the repo root (`/mnt/hdd/proj/high/in/CazzuBot`
> or wherever the checkout lives). Green gates: `uv run ruff check .`,
> `uv run basedpyright`, the targeted pytest files, and at the end
> `uv run pytest -q`.


Task 1 — Species keys, registry entries, art placeholders
---------------------------------------------------------

**Files:** modify `cazzubot/models.py`, `plugins/frogs/species.py`,
`plugins/frogs/assets.py`, `plugins/frogs/factory.py`
(`_frog_content` + `_default_capture_embed` art-None guards); create
placeholder PNGs; tests `tests/plugins/frogs/test_species.py`.

**Why:** the five species must exist as typed entities before any
behavior can attach. Mechanical slice (no RED cycle).

**Change Necessity:** species are code by design; adding species =
editing the registry.

**Impact/Compatibility:** `FrogItemKey` grows; `SPECIES` grows; art
becomes optional (cluster). Existing consumers of `species.art`
(`_frog_content`, capture embed, catalog thumbnail) are updated in this
task. `roll_species` weight math is unchanged.

**Steps (TDD Route: light — direct change + regression):**

1.  `cazzubot/models.py` — extend the enum:

~~~~ python
class FrogItemKey(Enum):
    """The valid frog species keys — code references them, never strings."""

    BASIC = "basic"
    POG = "pog"
    FROGGERS = "froggers"
    CLASSY = "classy"
    CLUSTER = "cluster"
~~~~

1.  `plugins/frogs/effects.py` — split the `frog_item_key` helper out of
    `db.FrogItem` so `effects.py` and `db.py` share exactly one derivation
    (no import cycle: `effects` imports neither `db` nor `species`-cyclic
    modules; `db` may import `effects`). Add to `plugins/frogs/effects.py`
    (this task only adds the helper; the effects in Task 2 use it):

~~~~ python
def frog_item_key(species_key: FrogItemKey, state: FrogState) -> str:
    """The inventory item string for a species in a state (one derivation)."""
    return f"frog:{species_key.value}:{state.value}"
~~~~

Then `plugins/frogs/db.py`:

~~~~ python
from .effects import frog_item_key
# ...in FrogItem:
    @property
    def key(self) -> str:
        """The derived inventory storage string for this frog stack."""
        return frog_item_key(self.species, self.state)
~~~~

1.  `plugins/frogs/species.py` — new field + five entries
    (the `spawn_effect` payload arrives in Task 5; the species carries
    no consume declaration — the item composes, see Task 3):

~~~~ python
from datetime import timedelta

from .effects import (
    EffectPayload,
    ReactionPayload,
    RolePayload,
)  # Task 2 classes


@dataclass(frozen=True, slots=True)
class Species:
    """One species — values are code, swappable only by editing them.

    The **entity**: what a frog *is* as a world/spawn object. ``art`` is
    optional — an uncatchable species (Cluster) has no visible art.
    ``catch_effect`` handles the catch side, ``spawn_effect`` replaces the
    catchable frog at spawn time (Cluster's explosion). Consumption is
    deliberately NOT here: the **item** composes what consuming does
    (owner 2026-08-28) — see ``items.py``.
    """

    key: FrogItemKey
    name: str
    rarity: str
    description: str
    spawn_weight: float
    catch_effect: EffectPayload | None
    spawn_effect: EffectPayload | None
    art: FrogAsset | None


SPECIES: tuple[Species, ...] = (
    Species(
        key=FrogItemKey.BASIC,
        name="Basic Frog",
        rarity="common",
        description="The most normalest frog of them all.",
        spawn_weight=1000.0,
        catch_effect=None,
        spawn_effect=None,
        art=FrogAsset.FROG_BASIC,
    ),
    Species(
        key=FrogItemKey.POG,
        name="Pog Frog",
        rarity="uncommon",
        description="A frog with a pog.",
        spawn_weight=200.0,
        catch_effect=None,  # ReactionPayload in Task 2
        spawn_effect=None,
        art=FrogAsset.FROG_POG,
    ),
    Species(
        key=FrogItemKey.FROGGERS,
        name="Froggers Frog",
        rarity="rare",
        description="A frog with a poggers.",
        spawn_weight=50.0,
        catch_effect=None,  # ReactionPayload in Task 2
        spawn_effect=None,
        art=FrogAsset.FROG_FROGGERS,
    ),
    Species(
        key=FrogItemKey.CLASSY,
        name="Classy Frog",
        rarity="rare",
        description="A frog with rather refined tastes.",
        spawn_weight=200.0,
        catch_effect=None,  # RolePayload in Task 2
        spawn_effect=None,
        art=FrogAsset.FROG_CLASSY,
    ),
    Species(
        key=FrogItemKey.CLUSTER,
        name="Cluster Frog",
        rarity="special",
        description="Be careful with this one… she's… spawning!",
        spawn_weight=300.0,
        catch_effect=None,
        spawn_effect=None,  # ClusterPayload in Task 5
        art=None,
    ),
)
~~~~

(The `spawn_effect` value is wired in Task 5; the consume-side payloads
land in Task 3 as the item-owned composition in `items.py` — the
species carries no consume declaration.)

1.  `plugins/frogs/assets.py` — declare the three new emoji assets:

~~~~ python
class FrogAsset(Enum):
    """Every asset the frogs plugin declares."""

    FROG_BASIC = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog-basic.png"
    )
    FROG_BASIC_FROZEN = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog-basic-frozen.png"
    )
    FROG_POG = AssetSpec(kind=AssetKind.EMOJI, path="assets/frog-pog.png")
    FROG_FROGGERS = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog-froggers.png"
    )
    FROG_CLASSY = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog-classy.png"
    )

    CATCH_BANNER = AssetSpec(
        kind=AssetKind.IMAGE, path="assets/caught.png"
    )
~~~~

Create placeholder files (1×1 PNG is fine; real art drops in later
re-syncs at boot — ROADMAP convention):

~~~~ bash
mkdir -p plugins/frogs/assets
uv run python - <<'PY'
from pathlib import Path

# a valid 1x1 transparent PNG placeholder
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806"
    "0000001f15c4890000000d4944415478da63f8cfc0f01f000504"
    "01fb99946f0000000049454e44ae426082"
)
for name in ("frog-pog", "frog-froggers", "frog-classy"):
    Path(f"plugins/frogs/assets/{name}.png").write_bytes(PNG)
PY
~~~~

1.  `plugins/frogs/factory.py` — guard optional art:

~~~~ python
async def _frog_content(bot: CazzuBot, species_key: FrogItemKey) -> str:
    """The spawned frog's message text: its art URL, else the species name."""
    species = by_key(species_key)
    art = (
        await bot.assets.get(species.art)
        if species is not None and species.art is not None
        else None
    )
    return art or (species.name if species is not None else "Frog")
~~~~

and in `_default_capture_embed` nothing changes (only reachable for
catchable species; `grant_catch_frog` guards `species.art`):

~~~~ python
species_art = (
    await bot.assets.get(species.art) or ""
)  # in grant_catch_frog
~~~~

→

~~~~ python
    species_art = (
        (await bot.assets.get(species.art) or "")
        if species.art is not None
        else ""
    )
~~~~

1.  Regression tests in `tests/plugins/frogs/test_species.py`:

~~~~ python
from cazzubot.models import FrogItemKey


def test_species_registry_has_frogmd_five() -> None:
    from plugins.frogs.species import SPECIES, by_key

    keys = {s.key for s in SPECIES}
    assert keys == {
        FrogItemKey.BASIC,
        FrogItemKey.POG,
        FrogItemKey.FROGGERS,
        FrogItemKey.CLASSY,
        FrogItemKey.CLUSTER,
    }
    weights = {s.key: s.spawn_weight for s in SPECIES}
    # FROG.md weights (relative)
    assert weights[FrogItemKey.BASIC] == 1000.0
    assert weights[FrogItemKey.POG] == 200.0
    assert weights[FrogItemKey.FROGGERS] == 50.0
    assert weights[FrogItemKey.CLASSY] == 200.0
    assert weights[FrogItemKey.CLUSTER] == 300.0
    # cluster is uncatchable-by-design: no art (spawn_effect wired in Task 5)
    cluster = by_key(FrogItemKey.CLUSTER)
    assert cluster is not None and cluster.art is None


def test_roll_species_respects_weights() -> None:
    import random

    from plugins.frogs.species import roll_species

    rng = random.Random(42)
    rolls = [roll_species(rng).key for _ in range(2000)]
    basic = rolls.count(FrogItemKey.BASIC) / len(rolls)
    froggers = rolls.count(FrogItemKey.FROGGERS) / len(rolls)
    assert 0.50 < basic < 0.65  # 1000/1750 ≈ 0.571 within noise
    assert 0.01 < froggers < 0.08  # 50/1750 ≈ 0.029
~~~~

(Task 1 asserts keys/weights/art only; the `spawn_effect is not None`
assertion lands with its wiring in Task 5. Item-owned consume
composition is asserted in Task 3.)

1.  **Verify:**

~~~~ bash
uv run pytest tests/plugins/frogs/test_species.py -q
uv run ruff check plugins/frogs cazzubot/models.py tests/plugins/frogs/test_species.py
uv run basedpyright
~~~~

Commit after verify:
`git -c commit.gpgsign=false commit -m "feat(frogs): declare the five FROG.md species (registry + art placeholders)"`.


Task 2 — FrogSeam, reaction/role effects, RoleConverger
-------------------------------------------------------

**Files:** create `plugins/frogs/seams.py`; modify
`plugins/frogs/effects.py`; tests `tests/plugins/frogs/test_effects.py`.

**Why:** Pog/Froggers and Classy need their timed consume behaviors — the
first real consumers of the effects engine from the frogs plugin.

**Change Necessity:** behavior does not exist; must be added as typed
engines (existing `EffectKey` registry convention).

**Impact/Compatibility:** effects.py stays hikari-free (CSR). Two new
seams: `FROG_REACTION` (internal), `CLASSY_ROLE` (external — needs a
registered converger before any publish; publish fail-fasts otherwise).
Plus `FrogEffect` (effect identities — the `source` of a contribution).
Consume hooks are **generic modifiers**: they take a `Scope` (member or
guild), so any caller — item composition today, an admin `/effect apply`
command later — can apply them to any target. Entity hooks (catch/spawn)
stay uid/cid-bound. No core changes: the engine's `(scope, seam, source)`
key already means “the same effect”; we feed it effect ids, not item ids.

**Steps (TDD Route: strict):**

1.  Write failing tests first in `tests/plugins/frogs/test_effects.py`
    (append; the file already covers `ExpEffect`):

~~~~ python
import pendulum
import pytest

from cazzubot.effects import ReapplyPolicy, Scope, ScopeKind
from plugins.frogs.effects import (
    EffectKey,
    ReactionPayload,
    RolePayload,
)
from plugins.frogs.seams import FrogEffect, FrogSeam


async def test_reaction_is_one_effect_across_items(full_bot) -> None:
    """Pog and Froggers are the same effect: one row, strongest value wins."""
    bot = full_bot
    now = pendulum.now("UTC")
    pog = ReactionPayload(chance=0.01, duration=pendulum.duration(hours=1))
    froggers = ReactionPayload(
        chance=0.07, duration=pendulum.duration(hours=1)
    )

    await EffectKey.REACTION.value.consume(
        bot,
        pog,
        scope=Scope.member(123),
        provenance="frog:pog:normal",
        amount=1,
        now=now,
    )
    # a stronger frog 5 min later: overwrites the value, keeps the window
    await EffectKey.REACTION.value.consume(
        bot,
        froggers,
        scope=Scope.member(123),
        provenance="frog:froggers:normal",
        amount=1,
        now=now.add(minutes=5),
    )
    contribs = await bot.effects.list(
        Scope.member(123), FrogSeam.FROG_REACTION, now=now.add(minutes=5)
    )
    assert len(contribs) == 1  # one effect, NOT one row per item
    assert contribs[0].source == FrogEffect.REACTION.key
    assert contribs[0].payload["chance"] == 0.07  # strongest wins
    assert (
        contribs[0].payload["from"] == "frog:froggers:normal"
    )  # provenance
    assert contribs[0].expires_at == now.add(
        hours=2, minutes=5
    )  # additive

    # a weaker consume never downgrades — it just extends the window
    await EffectKey.REACTION.value.consume(
        bot,
        pog,
        scope=Scope.member(123),
        provenance="frog:pog:normal",
        amount=1,
        now=now.add(minutes=30),
    )
    contribs = await bot.effects.list(
        Scope.member(123), FrogSeam.FROG_REACTION, now=now.add(minutes=30)
    )
    assert len(contribs) == 1
    assert contribs[0].payload["chance"] == 0.07  # still strongest
    assert contribs[0].expires_at == now.add(hours=3)  # 2h05m + 1h


async def test_role_consume_resolves_guild_role_and_publishes(
    full_bot,
) -> None:
    bot = full_bot
    bot.config.guild_kind = "development"  # dev guild role from FROG.md
    payload = RolePayload(
        role_dev=1542294599358353430,
        role_prod=1542293782588952696,
        duration=pendulum.duration(hours=3),
    )
    await EffectKey.ROLE.value.consume(
        bot,
        payload,
        scope=Scope.member(123),
        provenance="frog:classy:normal",
        amount=1,
        now=pendulum.now("UTC"),
    )
    contribs = await bot.effects.list(
        Scope.member(123), FrogSeam.CLASSY_ROLE
    )
    assert (
        contribs and contribs[0].payload["role_id"] == 1542294599358353430
    )
    assert contribs[0].source == FrogEffect.CLASSY_ROLE.key
    # and the world converged: the member now holds the role
    member = await bot.rest.fetch_member(bot.guild.id, 123)
    assert 1542294599358353430 in {r.id for r in member.roles}
~~~~

Verify RED: `uv run pytest tests/plugins/frogs/test_effects.py -q`
(import errors — the classes do not exist yet).

1.  Create `plugins/frogs/seams.py`:

~~~~ python
"""Frog effect seams — typed keys, never bare strings (SeamKey pattern).

Mirrors ``plugins/experience/logic.py::EffectSeam``: the enum member's
``key`` is the stored seam string; ``external`` marks seams whose
consequence touches Discord (only those get convergence jobs).
"""

from __future__ import annotations

from enum import Enum


class FrogSeam(Enum):
    """Frogs' input points on the effects engine."""

    # internal: message-time reaction chance (lazy expiry, no converger)
    FROG_REACTION = "frog_reaction"
    # external: a Discord role granted for a duration (converged by
    # plugins/frogs/effects.py::RoleConverger)
    CLASSY_ROLE = "classy_role"

    @property
    def key(self) -> str:
        """The derived storage string for this seam."""
        return self.value

    @property
    def external(self) -> bool:
        """True when the seam needs world-convergence (a Discord side effect)."""
        return self is FrogSeam.CLASSY_ROLE


class FrogEffect(Enum):
    """Frog effect identities — the `source` of a contribution.

    "The same effect" is keyed by (scope, seam, source); several items
    that ARE the same effect (Pog and Froggers = reaction chance) share
    one identity here, and the granting item travels in the payload as
    ``"from"`` provenance — the item never defines identity.
    """

    REACTION = "frog_reaction"
    CLASSY_ROLE = "classy_role"

    @property
    def key(self) -> str:
        """The derived storage string for this effect identity."""
        return self.value
~~~~

1.  Extend `plugins/frogs/effects.py` (module docstring note: the
    ROADMAP's planned `CLUSTER` is a spawn-side hook in this same module,
    with its factory dependency injected at load — Task 5):

~~~~ python
from cazzubot.effects import ReapplyPolicy, Scope  # top of imports

from .seams import FrogSeam

# payload durations carry the engine's type (datetime.timedelta);
# pendulum.duration() results are timedelta subclasses and also fit.
from datetime import timedelta
~~~~

~~~~ python
def frog_item_key(species_key: FrogItemKey, state: FrogState) -> str:
    """The inventory item string for a species in a state (one derivation).

    Mirrors ``db.FrogItem.key``, which delegates here, so a consume
    effect's seam ``source`` is byte-identical to the consumed item id.
    """
    return f"frog:{species_key.value}:{state.value}"
~~~~

~~~~ python
class ReactionEffect:
    """``reaction`` — a generic, composable state modifier: publish/merge
    the ONE reaction effect for a Scope.

    Generic by design (owner 2026-08-28): takes a **Scope**, so item
    composition applies it to the consuming member today, and a future
    admin `/effect apply` can apply it to any member/guild. Pog and
    Froggers are the same effect: both publish to the single
    ``(scope, seam, source)`` row under the shared effect identity
    ``FrogEffect.REACTION`` — never per-item sources — and the granting
    item travels in the payload as ``"from"`` provenance.

    While the window is active: the **strongest** chance wins (a
    Froggers overwrites a live Pog's 1% with 7%) and **every** consume
    extends the window additively (old ``expires_at`` plus its hour —
    FROG.md's "duration only, never stronger" spirit); after expiry a
    fresh consume starts anew. The value comparison is feature-side —
    the store never interprets payloads — so this hook fetches, compares
    and picks the write: REPLACE (new value + remaining rolling window)
    when strictly stronger, EXTEND (keep value, roll) otherwise.
    """

    async def catch(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """No catch behavior — the effect applies on consume only."""
        return None

    async def consume(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Publish/merge the shared reaction effect into ``scope``."""
        if not isinstance(payload, ReactionPayload):
            raise TypeError(
                "reaction effect requires ReactionPayload, got "
                f"{type(payload).__name__}"
            )
        seam = FrogSeam.FROG_REACTION
        source = FrogEffect.REACTION.key
        prov = {"chance": payload.chance, "from": provenance}
        existing = await bot.effects.fetch(scope, seam, source, now=now)
        if existing is None or payload.chance > float(
            existing.payload.get("chance", 0.0)
        ):
            # fresh, or strictly stronger: write the new value while
            # keeping the remaining window additive (REPLACE sets
            # expires_at = now + duration, so hand it remaining+duration)
            remaining = (
                (existing.expires_at - now)
                if existing is not None
                else pendulum.duration()
            )
            await bot.effects.publish(
                scope,
                seam,
                source,
                prov,
                duration=remaining + payload.duration,
                policy=ReapplyPolicy.REPLACE,
                now=now,
            )
        else:
            # weaker/equal: keep the value, extend the window additively
            await bot.effects.publish(
                scope,
                seam,
                source,
                prov,
                duration=payload.duration,
                policy=ReapplyPolicy.EXTEND,
                now=now,
            )


class RoleEffect:
    """``role`` — a generic, composable state modifier: publish the one
    classy-role effect for a Scope.

    ``FrogSeam.CLASSY_ROLE`` is an external seam: ``Effects.publish``
    runs the RoleConverger synchronously (role added now) and schedules
    the converge job at expiry (role removed then); explicit clear
    reverts instantly via EffectsClearedEvent. Normal and frozen Classy
    are the same effect (one row, EXTEND rolls the duration); the
    guild-side role id is resolved here from ``bot.config.guild_kind`` so
    the stored payload is the concrete role the converger must converge
    to, with the granting item as provenance. Scope-aware like every
    modifier — item composition passes the member scope; a future admin
    command could target any member.
    """

    async def catch(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        uid: int,
        species_key: FrogItemKey,
        now: pendulum.DateTime,
    ) -> None:
        """No catch behavior — the effect applies on consume only."""
        return None

    async def consume(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        scope: Scope,
        provenance: str,
        amount: int,
        now: pendulum.DateTime,
    ) -> None:
        """Publish the role grant into ``scope``."""
        if not isinstance(payload, RolePayload):
            raise TypeError(
                "role effect requires RolePayload, got "
                f"{type(payload).__name__}"
            )
        role_id = payload.role_id_for(bot.config.guild_kind)
        await bot.effects.publish(
            scope,
            FrogSeam.CLASSY_ROLE,
            source=FrogEffect.CLASSY_ROLE.key,
            payload={"role_id": role_id, "from": provenance},
            duration=payload.duration,
            policy=ReapplyPolicy.EXTEND,
            now=now,
        )


class RoleConverger:
    """World-reconciliation for the CLASSY_ROLE seam (member roles).

    Registered via ``bot.effects.register_converger`` at plugin load.
    Idempotent by construction: reads the seam's active contributions,
    computes the wanted role set, then diffs against the member's actual
    roles — adding missing, removing only roles this seam could grant
    (the bound ``role_ids`` — the same single source the species carry)
    that are no longer wanted. A member who left the guild fails
    fetch_member: logged and returned — the scheduler's converge job
    retries with backoff until the row expires/clears.
    """

    def __init__(self, role_ids: frozenset[int]) -> None:
        """Bind the role ids this seam may grant (see plugins/frogs/__init__.py).

        The ids derive from the species registry (every RolePayload's
        dev/prod ids) — computed in ``__init__.py``, which imports both
        ``species`` and ``effects``, so ``effects`` never imports
        ``species`` (the edge ``species → effects`` must stay one-way).
        """
        self._known = role_ids

    def _known_role_ids(self) -> frozenset[int]:
        """Every role id this seam is allowed to remove."""
        return self._known

    async def __call__(
        self, bot: "CazzuBot", scope: Scope, seam: str
    ) -> None:
        """Reconcile one member's classy roles to the active contributions."""
        if scope.kind is not ScopeKind.MEMBER:
            return
        contribs = await bot.effects.list(scope, FrogSeam.CLASSY_ROLE)
        wanted = {
            int(c["role_id"])
            for c in contribs
            if isinstance(c.get("role_id"), int)
        }
        try:
            member = await bot.rest.fetch_member(
                bot.config.guild_id, scope.id
            )
            current = {role.id for role in member.roles}
        except Exception:
            _log.exception(
                "classy role converge: cannot fetch member %s", scope.id
            )
            return
        reason = "classy frog role effect"
        for role_id in wanted - current:
            await bot.rest.add_role_to_member(
                bot.config.guild_id, scope.id, role_id, reason=reason
            )
        for role_id in (current & self._known_role_ids()) - wanted:
            await bot.rest.remove_role_from_member(
                bot.config.guild_id, scope.id, role_id, reason=reason
            )
~~~~

The import shape stays acyclic: ``species.py`` imports from
``effects.py`` (never the reverse); ``plugins/frogs/__init__.py``
imports both and builds the converger's role set from the registry:

~~~~ python
# plugins/frogs/__init__.py (Task 8 wires the registration)
from .effects import RoleConverger
from .items import classy_role_ids

_ROLE_IDS: frozenset[int] = classy_role_ids()  # from items.py — item-owned
~~~~

1.  GREEN: `uv run pytest tests/plugins/frogs/test_effects.py -q`.

2.  **Verify:**

~~~~ bash
uv run ruff check plugins/frogs tests/plugins/frogs/test_effects.py
uv run basedpyright
uv run pytest tests/core/test_csr_boundary.py tests/plugins/frogs/test_effects.py -q
~~~~

Commit:
`git -c commit.gpgsign=false commit -m "feat(frogs): reaction + role consume effects with FrogSeam seams and RoleConverger"`.


Task 3 — Item-owned consume composition + the new frog items
------------------------------------------------------------

**Files:** modify `plugins/frogs/items.py`; tests
`tests/plugins/frogs/test_items.py` (new).

**Why:** the six new consumables (Pog/Froggers/Classy × normal/frozen)
must exist as bare `Item` literals whose consume **composes** what
happens: exp (oracle) plus the item's composed effect applications
(owner 2026-08-28 — the item composes, effects modify).

**Change Necessity:** consumption glue currently grants exp only;
behavior for the new species must be reachable from `/inventory consume`.

**Impact/Compatibility:** composition data lives with the item
(`_SPECIES_CONSUME` beside the `frog_exp` oracle); species carry no
consume declaration; the modifiers are generic and scope-aware (this
same shape is what a future admin `/effect apply` uses); exp stays
oracle-owned; `frog_exp` gains rows (cluster deliberately absent →
catalog guards in Task 7). No cycles: `items → effects → seams` only.

**Steps (TDD Route: strict — behavioral composition first):**

1.  RED — `tests/plugins/frogs/test_items.py`:

~~~~ python
import pendulum

from cazzubot.models import FrogItemKey, FrogState
from plugins.frogs.items import _SPECIES_EXP, frog_exp


def test_new_species_exp_oracle_values() -> None:
    # D1/D2 defaults (owner-tunable)
    assert frog_exp(FrogItemKey.POG, FrogState.NORMAL) == 30
    assert frog_exp(FrogItemKey.FROGGERS, FrogState.NORMAL) == 300
    assert frog_exp(FrogItemKey.CLASSY, FrogState.NORMAL) == 200
    assert frog_exp(FrogItemKey.POG, FrogState.FROZEN) == 15
    assert frog_exp(FrogItemKey.FROGGERS, FrogState.FROZEN) == 150
    assert frog_exp(FrogItemKey.CLASSY, FrogState.FROZEN) == 100
    assert len(_SPECIES_EXP) == 4  # cluster has no exp (no item)


async def test_consume_composes_item_effects(full_bot) -> None:
    """Consuming a Pog grants exp AND applies the item's composed reaction effect."""
    from cazzubot.effects import Scope
    from plugins.frogs.items import FrogItems
    from plugins.frogs.seams import FrogSeam

    bot = full_bot
    uid = 123
    await bot.inventory.add(uid, "frog:pog:normal", 2)
    await FrogItems.POG.value.consume(bot, uid, 1)  # value = the Item
    assert (
        await bot.inventory.get(uid, "frog:pog:normal") == 1
    )  # glue does not decrement
    contribs = await bot.effects.list(
        Scope.member(uid), FrogSeam.FROG_REACTION
    )
    assert contribs and contribs[0].payload["chance"] == 0.01
~~~~

RED check: `uv run pytest tests/plugins/frogs/test_items.py -q`.

1.  `items.py` — oracle rows:

~~~~ python
# species × state -> exp per unit (D1/D2 defaults; owner-tunable)
_SPECIES_EXP: dict[FrogItemKey, dict[FrogState, int]] = {
    FrogItemKey.BASIC: {
        FrogState.NORMAL: 10,
        FrogState.FROZEN: 3,
    },
    FrogItemKey.POG: {
        FrogState.NORMAL: 30,
        FrogState.FROZEN: 15,
    },
    FrogItemKey.FROGGERS: {
        FrogState.NORMAL: 300,
        FrogState.FROZEN: 150,
    },
    FrogItemKey.CLASSY: {
        FrogState.NORMAL: 200,  # owner-set placeholder
        FrogState.FROZEN: 100,
    },
}
~~~~

1.  `items.py` — the item-owned composition: `_SPECIES_CONSUME` (the
    effect payloads an item applies — beside the oracle, so the item
    owns both its values and its composition) and `_consume_item`
    (exp first, then each composed modifier with the member scope, then
    the event):

~~~~ python
from datetime import timedelta

from cazzubot.effects import Scope

from .effects import ReactionPayload, RolePayload

# item-owned consume composition (owner 2026-08-28): what consuming an
# item does is the ITEM's decision. Values live in `_SPECIES_EXP`
# (oracle); the composed effect applications live here, beside them.
_SPECIES_CONSUME: dict[FrogItemKey, tuple[EffectPayload, ...]] = {
    FrogItemKey.BASIC: (),
    FrogItemKey.POG: (
        ReactionPayload(chance=0.01, duration=timedelta(hours=1)),
    ),
    FrogItemKey.FROGGERS: (
        ReactionPayload(chance=0.07, duration=timedelta(hours=1)),
    ),
    FrogItemKey.CLASSY: (
        RolePayload(
            role_dev=1542294599358353430,
            role_prod=1542293782588952696,
            duration=timedelta(hours=3),
        ),
    ),
}


def classy_role_ids() -> frozenset[int]:
    """Every role id the classy consume composition could grant.

    The single source the RoleConverger may remove (see
    plugins/frogs/__init__.py) — derived from this table so it can
    never drift from the items that actually grant roles.
    """
    ids: set[int] = set()
    for payloads in _SPECIES_CONSUME.values():
        for payload in payloads:
            if isinstance(payload, RolePayload):
                ids.add(payload.role_dev)
                ids.add(payload.role_prod)
    return frozenset(ids)


async def _consume_item(
    bot: "CazzuBot", uid: int, amount: int, item_id: str
) -> None:
    """The item-owned consume: exp, then the item's composed modifiers.

    The exp grant amount is derived from the item's own id via
    ``frog_exp`` — the single exp oracle — so a consume can never hand
    out a different value than the info card shows. The composed effect
    applications (`_SPECIES_CONSUME`) then run as generic scope-aware
    modifiers (member scope, the item id as provenance) — the ITEM
    decides what consumption does; the modifiers only modify state. The
    item reports itself as a :class:`FrogConsumedEvent` last, keeping
    the domain-observer path alive without the generic
    ``/inventory consume`` knowing frogs.
    """
    _, species_str, state_str = item_id.split(":")
    species_key = FrogItemKey(species_str)
    state = FrogState(state_str)
    exp = frog_exp(species_key, state) * amount

    now = pendulum.now("UTC")
    await exp_db.add_exp_log(
        bot.db, uid, exp, now, source=MemberExpLogSourceEnum.FROG
    )

    for payload in _SPECIES_CONSUME[species_key]:
        await payload.key.value.consume(
            bot,
            payload,
            scope=Scope.member(uid),
            provenance=item_id,
            amount=amount,
            now=now,
        )

    await bot.events.emit(
        FrogConsumedEvent(
            uid=uid,
            species_key=species_key,
            amount=amount,
            state=state,
            at=now.isoformat(),
        )
    )
~~~~

1.  `items.py` — blurb helper (display reads the same sources as the
    consume: the oracle + the item's own `_SPECIES_CONSUME` — they
    cannot drift):

~~~~ python
def _consume_blurb(species_key: FrogItemKey, state: FrogState) -> str:
    """The info card's "On consumption" text for a species' state."""
    parts = [f"Grants **{frog_exp(species_key, state)}** seasonal exp."]
    for payload in _SPECIES_CONSUME.get(species_key, ()):
        if isinstance(payload, ReactionPayload):
            parts.append(
                f"For the next hour, a **{payload.chance:.0%}** chance the "
                "bot reacts to your messages with the froggers emoji "
                "(10s cooldown)."
            )
        elif isinstance(payload, RolePayload):
            parts.append("Grants the **Classy** role for **3 hours**.")
    return " ".join(parts)
~~~~

Then `_consumption_field` returns `("On consumption", _consume_blurb(...))`.

1.  `items.py` — six new glue functions + item members (bare `Item`
    literals; frozen reuses the normal-species art per D8):

~~~~ python
async def _consume_pog_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:pog:normal`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:pog:normal")


async def _consume_pog_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:pog:frozen`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:pog:frozen")


async def _consume_froggers_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:froggers:normal`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:froggers:normal")


async def _consume_froggers_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:froggers:frozen`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:froggers:frozen")


async def _consume_classy_normal(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:classy:normal`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:classy:normal")


async def _consume_classy_frozen(
    bot: "CazzuBot", uid: int, amount: int
) -> None:
    """Consume glue for ``frog:classy:frozen`` (its own exp, per the id)."""
    await _consume_item(bot, uid, amount, "frog:classy:frozen")
~~~~

~~~~ python
class FrogItems(Enum):
    """Every frog inventory item — basic/pog/froggers/classy × normal/frozen.

    Cluster deliberately has no item: it can never be caught, so it can
    never be held or consumed (FROG.md: "User should not be able to
    acquire this item").
    """

    BASIC = Item(
        item_id="frog:basic:normal",
        display_name="Basic Frog",
        icon="🐸",
        description="The most normalest frog of them all.",
        icon_asset=FrogAsset.FROG_BASIC,
        consume=_consume_basic_normal,
        fields=(_consumption_field(FrogItemKey.BASIC, FrogState.NORMAL),),
    )
    BASIC_FROZEN = Item(
        item_id="frog:basic:frozen",
        display_name="Basic Frog (Frozen)",
        icon="🐸",
        description="A basic frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_BASIC_FROZEN,
        consume=_consume_basic_frozen,
        fields=(_consumption_field(FrogItemKey.BASIC, FrogState.FROZEN),),
    )
    POG = Item(
        item_id="frog:pog:normal",
        display_name="Pog Frog",
        icon="🐸",
        description="A frog with a pog.",
        icon_asset=FrogAsset.FROG_POG,
        consume=_consume_pog_normal,
        fields=(_consumption_field(FrogItemKey.POG, FrogState.NORMAL),),
    )
    POG_FROZEN = Item(
        item_id="frog:pog:frozen",
        display_name="Pog Frog (Frozen)",
        icon="🐸",
        description="A pog frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_POG,
        consume=_consume_pog_frozen,
        fields=(_consumption_field(FrogItemKey.POG, FrogState.FROZEN),),
    )
    FROGGERS = Item(
        item_id="frog:froggers:normal",
        display_name="Froggers Frog",
        icon="🐸",
        description="A frog with a poggers.",
        icon_asset=FrogAsset.FROG_FROGGERS,
        consume=_consume_froggers_normal,
        fields=(
            _consumption_field(FrogItemKey.FROGGERS, FrogState.NORMAL),
        ),
    )
    FROGGERS_FROZEN = Item(
        item_id="frog:froggers:frozen",
        display_name="Froggers Frog (Frozen)",
        icon="🐸",
        description="A froggers frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_FROGGERS,
        consume=_consume_froggers_frozen,
        fields=(
            _consumption_field(FrogItemKey.FROGGERS, FrogState.FROZEN),
        ),
    )
    CLASSY = Item(
        item_id="frog:classy:normal",
        display_name="Classy Frog",
        icon="🐸",
        description="A frog with rather refined tastes.",
        icon_asset=FrogAsset.FROG_CLASSY,
        consume=_consume_classy_normal,
        fields=(_consumption_field(FrogItemKey.CLASSY, FrogState.NORMAL),),
    )
    CLASSY_FROZEN = Item(
        item_id="frog:classy:frozen",
        display_name="Classy Frog (Frozen)",
        icon="🐸",
        description="A classy frog frozen solid by the seasonal freeze.",
        icon_asset=FrogAsset.FROG_CLASSY,
        consume=_consume_classy_frozen,
        fields=(_consumption_field(FrogItemKey.CLASSY, FrogState.FROZEN),),
    )
~~~~

1.  The species stays entity-only: no consume payloads are wired on
    `SPECIES` (Task 1 already dropped the field) — the composition lives
    in `_SPECIES_CONSUME` above. Durations are `datetime.timedelta`
    (`pendulum.duration` also works); the engine accepts both.

2.  GREEN + regression:

~~~~ bash
uv run pytest tests/plugins/frogs/test_items.py tests/plugins/frogs/test_effects.py -q
~~~~

1.  **Verify:**

~~~~ bash
uv run ruff check plugins/frogs tests/plugins/frogs
uv run basedpyright
uv run pytest tests/plugins/frogs -q
~~~~

Commit:
`git -c commit.gpgsign=false commit -m "feat(frogs): frog items for pog/froggers/classy with item-owned consume composition"`.


Task 4 — Reaction listener
--------------------------

**Files:** create `plugins/frogs/reactions.py`; modify
`plugins/frogs/__init__.py` (`extensions` += it); tests
`tests/plugins/frogs/test_reactions.py` (new).

**Why:** the “bot reacts to this user's messages with the froggers emoji”
behavior from FROG.md.

**Change Necessity:** the seam only stores data — nothing acts on it yet.

**Impact/Compatibility:** guild-scoped via `guild_listener` (never fires
for the other guild / DMs); skips bots; internal seam (no converger);
in-memory cooldown (D4); no-ops harmlessly until the froggers emoji is
published (D5).

**Steps (TDD Route: strict):**

1.  RED — `tests/plugins/frogs/test_reactions.py`:

~~~~ python
import time

import pytest

from cazzubot.effects import Scope
from plugins import frogs as frogs_pkg
from plugins.frogs import reactions
from plugins.frogs.seams import FrogEffect, FrogSeam
from tests.fakes import FakeMessageCreateEvent

_EMOJI = "<:frog_froggers:9001>"


@pytest.fixture
def seeded_roll(monkeypatch) -> None:
    """Force `random.random()` to 0.0 (always roll) / 1.0 (never)."""
    store: dict[str, float] = {}

    class _Fixed:
        def random(self) -> float:
            return store.get("v", 0.0)

        def set(self, v: float) -> None:
            store["v"] = v

    fixed = _Fixed()  # type: ignore[attr-defined]
    monkeypatch.setattr(reactions.random, "random", fixed.random)
    reactions._last_react.clear()
    monkeypatch.setattr(reactions, "_last_react", {})
    return fixed


async def _seed_reaction(bot, uid: int, chance: float) -> None:
    await bot.effects.publish(
        Scope.member(uid),
        FrogSeam.FROG_REACTION,
        source=FrogEffect.REACTION.key,
        payload={"chance": chance},
        duration=None,
        now=None,
    )


async def test_message_with_reaction_contribution_reacts(
    full_bot,
    seeded_roll,
) -> None:
    bot = full_bot
    # publish the froggers emoji asset row directly (assets.get reads it)
    await bot.db.execute(
        "INSERT OR REPLACE INTO asset (key, path, kind, hash, url) "
        "VALUES ('FrogAsset.FROG_FROGGERS'  # asset_key(member) = EnumClass.MEMBER, ?, 'emoji', ?, ?)",
        "assets/frog-froggers.png",
        "x",
        _EMOJI,
    )
    await _seed_reaction(bot, 123, 1.0)
    before = len(bot.rest.reactions)
    await _dispatch_message(bot, uid=123)
    assert len(bot.rest.reactions) == before + 1
    channel_id, message_id, emoji = bot.rest.reactions[-1]
    assert emoji == _EMOJI


async def test_cooldown_blocks_second_react(full_bot, seeded_roll) -> None:
    bot = full_bot
    await bot.db.execute(
        "INSERT OR REPLACE INTO asset (key, path, kind, hash, url) "
        "VALUES ('FrogAsset.FROG_FROGGERS'  # asset_key(member) = EnumClass.MEMBER, ?, 'emoji', ?, ?)",
        "assets/frog-froggers.png",
        "x",
        _EMOJI,
    )
    await _seed_reaction(bot, 123, 1.0)
    await _dispatch_message(bot, uid=123)
    n_after_first = len(bot.rest.reactions)
    await _dispatch_message(bot, uid=123)  # within 10s
    assert len(bot.rest.reactions) == n_after_first


async def test_no_contribution_never_reacts(full_bot, seeded_roll) -> None:
    bot = full_bot
    await _dispatch_message(bot, uid=999)
    assert bot.rest.reactions == []
~~~~

plus the shared delivery helper for the tests above (in the same
file):

~~~~ python
async def _dispatch_message(bot, uid: int) -> None:
    """Deliver a guild-style message event straight to the listener.

    The listener reads `event.message` fields (like the experience
    listener) plus `event.app`; `FakeMessageCreateEvent` (the fakes'
    hikari stand-in) around a `FakeMessage` drives it without the
    gateway.
    """
    from tests.fakes import FakeMember, FakeMessageCreateEvent

    from tests.fakes import FakeMember, FakeMessage

    author = FakeMember(id=uid, name="tester")
    message = FakeMessage(
        id=222, channel_id=111, author=author, guild_id=bot.config.guild_id
    )
    event = FakeMessageCreateEvent(message=message, app=bot)
    await reactions.on_message(event)
~~~~

Verify RED: `uv run pytest tests/plugins/frogs/test_reactions.py -q`
(module import missing).

1.  Create `plugins/frogs/reactions.py`:

~~~~ python
"""Frog reactions — the message-time listener for FrogSeam.FROG_REACTION.

A user with an active reaction contribution (Pog/Froggers consumed) has
a per-message chance the bot reacts to their message with the froggers
emoji. The seam only stores the chance; this listener is the consumer:

- fold: the **strongest** active contribution decides the chance (max —
  stacking reaction frogs never strengthens, mirroring the "duration
  only, never stronger" rule).
- throttle: one reaction per user per ``_REACT_COOLDOWN`` seconds
  (10s per FROG.md). The cooldown is in-memory by design: a restart at
  worst allows one extra reaction; no table is worth that.
- gracefully no-ops while the froggers emoji asset is unpublished.
"""

from __future__ import annotations

import logging
import random
import time
from typing import cast

import hikari
import lightbulb

from cazzubot.bot import CazzuBot
from cazzubot.effects import Scope
from cazzubot.listeners import guild_listener

from .assets import FrogAsset
from .seams import FrogSeam

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

# seconds between reactions per user (FROG.md: "10 second cooldown per
# react") — also the practical Discord rate-limit guard.
_REACT_COOLDOWN = 10.0

# uid -> epoch of the last reaction; in-memory per D4.
_last_react: dict[int, float] = {}


@guild_listener(loader, hikari.MessageCreateEvent)
async def on_message(event: hikari.MessageCreateEvent) -> None:
    """Roll the reaction chance for the message author, throttled.

    Reads ``event.message`` (not the event's convenience props) so the
    offline fakes drive it exactly like the experience listener.
    """
    message = event.message
    author = message.author
    if author is None or author.is_bot:
        return
    bot = cast(CazzuBot, event.app)
    uid = author.id
    # one row by construction (the reaction effect is keyed by effect
    # identity, not by item) — read it directly, no fold
    contribs = await bot.effects.list(
        Scope.member(uid), FrogSeam.FROG_REACTION
    )
    if not contribs:
        return
    chance = float(contribs[0].payload.get("chance", 0.0))
    if chance <= 0.0 or random.random() >= chance:
        return
    if time.time() - _last_react.get(uid, 0.0) < _REACT_COOLDOWN:
        return
    emoji = await bot.assets.get(FrogAsset.FROG_FROGGERS)
    if emoji is None:
        return  # froggers emoji not published yet — nothing to react with
    try:
        await bot.rest.add_reaction(message.channel_id, message.id, emoji)
        _last_react[uid] = time.time()
    except hikari.NotFoundError:
        pass  # message or emoji vanished between pull and react — fine
    except hikari.RateLimitError:
        _log.warning("frog reaction rate-limited; skipping")
~~~~

1.  Wire the extension module — `plugins/frogs/__init__.py`:

~~~~ python
    extensions = ["plugins.frogs.extension", "plugins.frogs.reactions"]
~~~~

1.  GREEN + verify:

~~~~ bash
uv run pytest tests/plugins/frogs/test_reactions.py -q
uv run ruff check plugins/frogs tests/plugins/frogs/test_reactions.py
uv run basedpyright
uv run pytest tests/core/test_csr_boundary.py tests/integration/test_guard_driver.py -q
~~~~

Commit:
`git -c commit.gpgsign=false commit -m "feat(frogs): message reaction listener for the reaction seam"`.


Task 5 — Cluster Frog explosion
-------------------------------

**Files:** modify `plugins/frogs/effects.py` (`ClusterEffect` +
`ClusterPayload` + `EffectKey.CLUSTER`), `plugins/frogs/species.py`
(wire `spawn_effect=ClusterPayload()`), `plugins/frogs/factory.py`
(spawn short-circuit + uncatchable guard), `plugins/frogs/__init__.py`
(inject `ClusterEffect.spawn_impl` on load), `tests/fakes.py`
(`fetch_guild_channels`); tests `tests/plugins/frogs/test_cluster.py`.

**Why:** FROG.md's Cluster — uncatchable, bursts 4–10 Basic Frogs
nearby.

**Change Necessity:** no spawn-side hook exists; exploding must not post
a catchable Cluster.

**Impact/Compatibility:** child spawns are real catchable Basic frogs
(existing path, forced species) run as tracked background tasks — the
scheduler handler returns immediately (never blocks on 4–10 persists).
`/frog spawn`/`fake species=cluster` explodes too (owner testing).
`effects.py` stays hikari-free: the blast zone compares channel types to
the **numeric** GUILD\_TEXT value (0) and spawns children through the
injected `spawn_impl` callback — `effects → factory` would be a cycle
(`factory → species → effects`), so the plugin injects it at load.

**Steps (TDD Route: strict):**

1.  `tests/fakes.py` — add `fetch_guild_channels` to `FakeRest`:

~~~~ python
    async def fetch_guild_channels(self, guild_id: int) -> list[FakeChannel]:
        """The guild's channels (the cluster blast zone reads this)."""
        guild = self.guilds.get(guild_id)
        if guild is None:
            return []
        return list(guild.channels.values())
~~~~

(Confirm the attribute name in `FakeRest.__init__` — `self.guilds`
vs per-guild stores — before writing; the test seeds channels there.)

1.  `tests/plugins/frogs/test_cluster.py`:

~~~~ python
import asyncio

import pendulum

from cazzubot.models import FrogItemKey
from plugins.frogs.effects import ClusterEffect, ClusterPayload
from tests.fakes import FakeChannel


async def test_cluster_spawn_bursts_basics_into_zone(
    full_bot,
    monkeypatch,
) -> None:
    """A cluster spawn posts N child Basic frogs, never a cluster frog."""
    bot = full_bot
    # three text channels: id 9 (down), 10 (center), 11 (up)
    gid = bot.config.guild_id
    guild = bot.rest.guilds[gid]
    for cid_, pos in ((9, 1), (10, 2), (11, 3)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        guild.channels[cid_] = channel

    spawned: list[tuple[int, FrogItemKey]] = []

    async def fake_spawn(b, persist, cid=None, species_key=None) -> bool:
        spawned.append((cid, species_key or FrogItemKey.BASIC))
        return False

    effect = ClusterEffect()
    effect.spawn_impl = fake_spawn  # type: ignore[assignment]
    monkeypatch.setattr(
        "plugins.frogs.effects.random",
        __import__("random").Random(7),
    )

    await effect.spawn(
        bot,
        ClusterPayload(),
        cid=10,
        guild_id=gid,
        persist=30,
        now=pendulum.now("UTC"),
    )
    # children are tracked background tasks — drain the loop
    for _ in range(100):
        if len(spawned) >= 4:
            break
        await asyncio.sleep(0.01)

    assert 4 <= len(spawned) <= 10
    assert {key for _, key in spawned} == {FrogItemKey.BASIC}
    assert {cid_ for cid_, _ in spawned} <= {9, 10, 11}


async def test_cluster_zone_ignores_non_text_and_outside_channels(
    full_bot,
) -> None:
    """Only text channels within the radius count (FROG.md: ±2)."""
    bot = full_bot
    gid = bot.config.guild_id
    guild = bot.rest.guilds[gid]
    for cid_, pos in ((1, 0), (9, 1), (10, 2), (11, 3), (99, 9)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        if cid_ == 99:
            channel.type = None  # not a text channel
        guild.channels[cid_] = channel

    effect = ClusterEffect()
    zone = await effect._zone(bot, gid, cid=10, radius=2)  # type: ignore[attr-defined]
    assert [entry[0] for entry in zone] == [1, 9, 10, 11]  # 99 excluded
~~~~

RED: `uv run pytest tests/plugins/frogs/test_cluster.py -q`.

1.  `plugins/frogs/effects.py` — the spawn hook + payload (registry home;
    the enum member's value IS the handler, per the convention):

~~~~ python
import asyncio
import random
from collections.abc import Awaitable, Callable

# hikari-free channel-type check: hikari.ChannelType.GUILD_TEXT == 0 and
# the REST returns channel objects whose ``type`` is that value.
_GUILD_TEXT = 0


class ClusterEffect:
    """``cluster`` — the spawn hook: burst child frogs into nearby channels.

    Children are spawned through ``spawn_impl`` — the factory's
    ``spawn_and_wait`` — which this module cannot import (the edge
    ``effects → factory`` would cycle through species). The plugin's
    ``on_load`` injects it (see plugins/frogs/__init__.py), keeping the
    import graph acyclic and hikari out of this service module. Children
    run as **tracked background tasks** so the scheduler handler returns
    immediately instead of blocking on up to 10 capture waits.
    """

    # spawn_and_wait(bot, persist, cid=..., species_key=...), set on load
    spawn_impl: Callable[..., Awaitable[None]] | None = None
    # strong references keep background child tasks alive until done
    _background: set[asyncio.Task] = set()

    async def spawn(
        self,
        bot: "CazzuBot",
        payload: EffectPayload,
        *,
        cid: int,
        guild_id: int,
        persist: int,
        now: pendulum.DateTime,
    ) -> None:
        """Explode: 4–10 child Basic frogs into the text channels around ``cid``."""
        if not isinstance(payload, ClusterPayload):
            raise TypeError(
                "cluster effect requires ClusterPayload, got "
                f"{type(payload).__name__}"
            )
        if self.spawn_impl is None:
            _log.error(
                "cluster effect has no spawn_impl — plugin on_load missed"
            )
            return
        zone = await self._zone(bot, guild_id, cid, payload.radius)
        if not zone:
            _log.warning(
                "cluster spawn channel %s outside text channels", cid
            )
            return
        count = random.randint(payload.min_spawns, payload.max_spawns)
        targets = [random.choice(zone) for _ in range(count)]
        _log.info(
            "cluster frog bursts %d basic(s) across %d channel(s)",
            count,
            len(zone),
        )
        for target in targets:
            self._start_child(bot, payload, persist, target)
            if payload.delay > 0:
                await asyncio.sleep(payload.delay)

    async def _zone(
        self, bot: "CazzuBot", guild_id: int, cid: int, radius: int
    ) -> list[tuple[int, int]]:
        """(channel_id, position) pairs within ``radius`` of ``cid``.

        Text channels only, ordered by (position, id); the zone is the
        slice ±``radius`` around the spawn channel, clamped at both ends.
        """
        channels = await bot.rest.fetch_guild_channels(guild_id)
        texts = [
            (channel.id, getattr(channel, "position", 0) or 0)
            for channel in channels
            if getattr(channel, "type", None) == _GUILD_TEXT
        ]
        texts.sort(key=lambda entry: (entry[1], entry[0]))
        ids = [entry[0] for entry in texts]
        if cid not in ids:
            return []
        index = ids.index(cid)
        return texts[max(0, index - radius) : index + radius + 1]

    def _start_child(
        self,
        bot: "CazzuBot",
        payload: "ClusterPayload",
        persist: int,
        target: tuple[int, int],
    ) -> None:
        """Fire one child Basic-frog spawn as a tracked background task."""
        child_persist = persist or payload.persist
        task = asyncio.create_task(
            self.spawn_impl(  # type: ignore[misc]  # injected on load
                bot,
                child_persist,
                cid=target[0],
                species_key=payload.child_species,
            )
        )
        self._background.add(task)
        task.add_done_callback(self._background.discard)


@dataclass(frozen=True, slots=True)
class ClusterPayload:
    """The ``cluster`` spawn effect's configuration (FROG.md defaults)."""

    key = EffectKey.CLUSTER

    min_spawns: int = 4
    max_spawns: int = 10
    radius: int = 2  # text channels up AND down from the spawn channel
    delay: float = 0.75  # seconds between child spawns (rate-limit guard)
    child_species: FrogItemKey = FrogItemKey.BASIC
    persist: int = 30  # child lifetime when the spawning ctx omits persist
~~~~

and the registry gains the member:

~~~~ python
class EffectKey(Enum):
    """The effect registry — each member's value IS its handler.

    REACTION/ROLE are the generic consume modifiers; CLUSTER joins in
    Task 5 (spawn-side entity hook). ``ExpEffect``/``EXP`` stays in the
    codebase but is deliberately unused: exp grant is item-owned
    behavior (oracle), not a state modifier — slated for removal in a
    follow-up (see Task 9 docs note).
    """

    EXP = ExpEffect()
    REACTION = ReactionEffect()
    ROLE = RoleEffect()
    CLUSTER = ClusterEffect()
~~~~

1.  `plugins/frogs/species.py` — wire the cluster spawn payload (data
    comes from effects.py — no import cycle):

~~~~ python
from .effects import ClusterPayload

    Species(
        key=FrogItemKey.CLUSTER,
        ...  # elided fields identical to Task 1's literal
        spawn_effect=ClusterPayload(),
    ),
~~~~

1.  `plugins/frogs/factory.py` — spawn short-circuit (before any message)
     -  uncatchable guard:

~~~~ python
    if species_key is None:
        species_key = roll_species().key
    species = by_key(species_key)
    if species is not None and species.spawn_effect is not None:
        # spawn-effect species (Cluster) never post a catchable frog —
        # their hook runs instead and this function returns immediately
        payload = species.spawn_effect
        handler = getattr(payload.key.value, "spawn", None)
        if handler is not None:
            await handler(
                bot,
                payload,
                cid=cid,
                guild_id=bot.config.guild_id,
                persist=persist,
                now=pendulum.now("UTC"),
            )
        return False
    menu = FrogCatchMenu(bot, cid, species_key)
~~~~

and in `FrogCatchMenu.catch`, right after `species = by_key(...)`
(defensive — a stale Cluster button from a previous build must never
grant or log a phantom stack):

~~~~ python
species = by_key(self.species_key)
if species is None:
    _log.error(
        "capture of unknown species %r (uid=%s)",
        self.species_key.value,
        uid,
    )
    return
if species.spawn_effect is not None:
    await mctx.respond(
        "This frog cannot be caught — it already burst into its children!",
        flags=hikari.MessageFlag.EPHEMERAL,
    )
    return
~~~~

1.  `plugins/frogs/__init__.py` — inject the spawn implementation when
    the plugin loads (with the other registrations from Task 8):

~~~~ python
    from . import factory as frog_factory
    from .effects import ClusterEffect

    ClusterEffect.spawn_impl = frog_factory.spawn_and_wait
~~~~

and clear it on unload (`ClusterEffect.spawn_impl = None`).

1.  GREEN:

~~~~ bash
uv run pytest tests/plugins/frogs/test_cluster.py tests/plugins/frogs/test_species.py -q
~~~~

(The species-registry regression from Task 1 —
`cluster.spawn_effect is not None` — goes green now.)

1.  **Verify:**

~~~~ bash
uv run ruff check plugins/frogs tests/plugins/frogs tests/fakes.py
uv run basedpyright
uv run pytest tests/core/test_csr_boundary.py tests/core/test_db_boundary.py -q
~~~~

Commit:
`git -c commit.gpgsign=false commit -m "feat(frogs): cluster frog spawn explosion (uncatchable burst of basics)"`.


Task 6 — Quarterly “use it or lose it” reset
--------------------------------------------

**Files:** modify `plugins/frogs/db.py` (`freeze_frogs` becomes
`season_reset_frogs`), `plugins/frogs/__init__.py` (handler call);
tests `tests/plugins/frogs/test_cadences.py`.

**Why:** owner rule (2026-08-28): *all frogs at season end get turned
into basic frogs* — species identity and buffs are “use it or lose it”.

**Change Necessity:** the existing quarterly fold keeps each species
around devalued (normal→frozen); the new rule collapses every species
into Basic, so the fold must change while the tag/cadence/arming stay.

**Impact/Compatibility:** the `quarterly` tag, `QUARTERLY_CADENCE` and
re-arm logic are unchanged (same first-of-season rollover); only the DB
fold changes. `FrogState.FROZEN` and the frozen item definitions stay:
Basic's own devaluation still makes frozen basics, and legacy
non-basic frozen stacks (rows created before this rule) must remain
consumable — the reset merely stops producing new ones. No migration:
existing per-species stacks simply convert at the next rollover.

**Steps (TDD Route: light — semantics change + regression):**

1.  `plugins/frogs/db.py` — replace `freeze_frogs`:

~~~~ python
async def season_reset_frogs(db: Database) -> None:
    """Quarterly: every frog becomes a Basic Frog ("use it or lose it").

    Owner rule (2026-08-28): at season end species identity and buffs
    do not carry over. Every non-basic stack (normal OR frozen) folds
    into ``frog:basic:normal``, then Basic's own soft reset folds the
    normal stack into frozen (10->3 exp). After a reset a member holds
    ``frog:basic:frozen`` only. Idempotent: a second run finds no
    non-basic stacks and no basic-normal stacks to fold.
    """
    basic_normal = FrogItem(FrogItemKey.BASIC, FrogState.NORMAL)
    basic_frozen = FrogItem(FrogItemKey.BASIC, FrogState.FROZEN)
    for species in SPECIES:
        if species.key is FrogItemKey.BASIC:
            continue
        await inventory.move_all(
            db, FrogItem(species.key, FrogState.NORMAL), basic_normal
        )
        await inventory.move_all(
            db, FrogItem(species.key, FrogState.FROZEN), basic_normal
        )
    await inventory.move_all(db, basic_normal, basic_frozen)
~~~~

1.  `plugins/frogs/__init__.py` — `on_quarterly_due` calls the new
    name (the tag, cadence and re-arm stay untouched):

~~~~ python
    await db.season_reset_frogs(bot.db)
~~~~

~~~~
(update the module comment that says “freeze” to “season reset”.)
~~~~

1.  Tests — `tests/plugins/frogs/test_cadences.py`: the three existing
    basic-freeze tests keep passing unchanged (a basic-normal-only
    member still ends with basic:frozen); add the species conversion:

~~~~ python
async def test_quarterly_reset_converts_every_species_to_basic(
    bot: CazzuBot,
) -> None:
    """Use it or lose it: pog/froggers/classy stacks become Basic."""
    for key in (FrogItemKey.POG, FrogItemKey.FROGGERS, FrogItemKey.CLASSY):
        await frog_db.modify_inventory(bot.db, 1, key, FrogState.NORMAL, 2)
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.POG, FrogState.FROZEN, 1
    )

    await on_quarterly_due(bot, {})

    for key in (FrogItemKey.POG, FrogItemKey.FROGGERS, FrogItemKey.CLASSY):
        assert await frog_db.get_inventory(bot.db, 1, key) == 0
        assert (
            await frog_db.get_inventory(bot.db, 1, key, FrogState.FROZEN)
            == 0
        )
    # 2+2+2 (normal) + 1 (pog frozen) = 7 basics — all frozen after the
    # basic devaluation step
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.BASIC, FrogState.NORMAL
        )
        == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.BASIC, FrogState.FROZEN
        )
        == 7
    )
~~~~

1.  Verify:

~~~~ bash
uv run pytest tests/plugins/frogs/test_cadences.py tests/plugins/frogs -q
uv run ruff check plugins/frogs
uv run basedpyright
~~~~

Commit:
`git -c commit.gpgsign=false commit -m "feat(frogs): quarterly season reset folds every species into basic frogs (use it or lose it)"`.


Task 7 — Catalog + extension display
------------------------------------

**Files:** modify `plugins/frogs/extension.py`; tests
`tests/plugins/frogs/test_extension.py`.

**Why:** `/frog catalog` and `/inventory info` must describe the new
species accurately (FROG.md behaviors), and Cluster must not render an
exp line (no item/exp).

**Change Necessity:** display currently reads `frog_exp` unconditionally
— a KeyError for Cluster.

**Impact/Compatibility:** catalog shows spawn-effect species with a
burst note; consume text comes from `_consume_blurb` (same source as the
grant — no drift).

**Steps (TDD Route: light — regression + mechanical):**

1.  `test_extension.py` — regression (catalog renders all five
    species; cluster shows the burst note, never an exp line) and update
    the existing `test_frog_catalog_lists_species` (Basic is renamed
    from “Leaf Frog”, and the catalog now has **5** fields):

~~~~ python
from plugins.frogs.extension import Catalog
from tests.fakes import FakeContext, invoke_command


async def test_frog_catalog_lists_all_frogmd_species(
    bot: CazzuBot,
    ctx: FakeContext,
) -> None:
    await invoke_command(Catalog(), ctx)

    embed = ctx.sent[-1].embed
    assert embed is not None
    assert embed.title == "Frog Species Catalog"
    names = [field.name for field in embed.fields]
    assert any("Basic Frog" in name for name in names)
    assert any("Pog Frog" in name for name in names)
    assert any("Froggers Frog" in name for name in names)
    assert any("Classy Frog" in name for name in names)
    assert any("Cluster Frog" in name for name in names)
    # cluster: burst note, no "Consume:" line (no item/exp exists)
    cluster_field = next(
        field for field in embed.fields if "Cluster Frog" in field.name
    )
    assert "Cannot be caught" in cluster_field.value
    assert "Consume:" not in cluster_field.value
    # classy: exp line renders the oracle value (D1 default: 200)
    classy_field = next(
        field for field in embed.fields if "Classy Frog" in field.name
    )
    assert "**`200`** exp" in classy_field.value
~~~~

(Existing `test_frog_catalog_lists_species` is updated in the same
task: Basic shows its new name and the field count becomes 5.)

1.  `extension.py` `Catalog.invoke` — branch:

~~~~ python
        for species in SPECIES:
            if thumbnail_art is None:
                thumbnail_art = await bot.assets.get(species.art)
                if thumbnail_art is not None:
                    embed.set_thumbnail(thumbnail_art)
            if species.spawn_effect is not None:
                # uncatchable: never a consume line (no item/exp exists)
                value = (
                    f"{species.description}\nRarity: {species.rarity}\n"
                    "Cannot be caught — it bursts into Basic Frogs nearby!"
                )
            else:
                value = f"{species.description}\nRarity: {species.rarity}"
                normal_exp = frog_exp(species.key, FrogState.NORMAL)
                frozen_exp = frog_exp(species.key, FrogState.FROZEN)
                value += (
                    f"\nConsume: **`{normal_exp}`** exp (normal) / "
                    f"**`{frozen_exp}`** exp (frozen)"
                )
            embed.add_field(
                name=f"{species.name} (`{species.key.value}`)", value=value
            )
~~~~

(The `thumbnail_art` guard needs `species.art` None-check too:

~~~~ python
            if thumbnail_art is None and species.art is not None:
~~~~

)

1.  **Verify:**

~~~~ bash
uv run pytest tests/plugins/frogs/test_extension.py -q
uv run ruff check plugins/frogs
uv run basedpyright
~~~~

Commit:
`git -c commit.gpgsign=false commit -m "feat(frogs): catalog describes new species (cluster burst note, no exp line)"`.


Task 8 — Driver end-to-end tests + plugin load wiring
-----------------------------------------------------

**Files:** modify `plugins/frogs/__init__.py` (converger registration,
`EffectsClearedEvent` subscription, `ClusterEffect.spawn_impl`
injection, unsubscribe on unload); `tests/integration/test_frog_driver.py`.

**Why:** the interactive flows must be proven through the real
lightbulb routing (`tests/driver.py`), and the external seam must be
registered before any Classy publish can succeed (the engine fail-fasts
otherwise).

**Change Necessity:** behavior touches Discord state (roles) and the
menu pipeline; the convention is to verify such changes end-to-end
offline.

**Impact/Compatibility:** `on_load` now registers the converger +
subscription + spawn\_impl; `on_unload` unregisters all three.

**Steps (TDD Route: strict — driver tests first):**

1.  `plugins/frogs/__init__.py`:

~~~~ python
from cazzubot.effects import EffectsClearedEvent, Scope, ScopeKind

from .effects import (
    ClusterEffect,
    RoleConverger,
    RolePayload,
)
from . import factory as frog_factory
from .species import SPECIES

_ROLE_IDS: frozenset[int] = classy_role_ids()  # from items.py — item-owned


class FrogsPlugin(Plugin):
    ...  # existing class body unchanged apart from the line below
    extensions = ["plugins.frogs.extension", "plugins.frogs.reactions"]

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        # …existing resets/arms…
        ClusterEffect.spawn_impl = frog_factory.spawn_and_wait
        self._converger = RoleConverger(_ROLE_IDS)
        bot.effects.register_converger(
            FrogSeam.CLASSY_ROLE, self._converger
        )
        self._unsub_cleared = bot.events.on(
            EffectsClearedEvent, self._on_effects_cleared
        )

    @override
    async def on_unload(self, bot: CazzuBot) -> None:
        ClusterEffect.spawn_impl = None
        bot.effects.unregister_converger(FrogSeam.CLASSY_ROLE)
        self._unsub_cleared()

    async def _on_effects_cleared(
        self, event: EffectsClearedEvent
    ) -> None:
        """Instant role revert when the effects engine explicitly clears.

        The engine emits the event without an app, so the bot is captured
        on the plugin at load (``self._bot``).
        """
        if event.scope.kind is not ScopeKind.MEMBER:
            return
        if (
            event.seam is not None
            and event.seam != FrogSeam.CLASSY_ROLE.key
        ):
            return
        await self._converger(
            self._bot, event.scope, FrogSeam.CLASSY_ROLE.key
        )
~~~~

(``on_load`` must also store the bot: ``self._bot = bot`` — add it next
to the existing resets, alongside the ``self._unsub_cleared`` token;
``on_unload`` clears ``spawn_impl``, unregisters the converger and calls
``self._unsub_cleared()`` with the stored bot.)

1.  `tests/integration/test_frog_driver.py` — add (concrete driver
    flows following `test_confirm_menu_driver.py`):

~~~~ python
import asyncio

from cazzubot.effects import Scope
from tests.driver import press_button, run_slash, wait_for_menu
from tests.fakes import rest_of

from plugins.frogs.seams import FrogEffect, FrogSeam

# the dev-guild classy role (FROG.md); tests run guild_kind=development
_CLASSY_ROLE_DEV = 1542294599358353430


async def test_consume_pog_via_driver_publishes_reaction_seam(
    full_bot: CazzuBot,
) -> None:
    """/inventory consume of a Pog grants exp + reaction contribution."""
    await full_bot.db.execute(
        """
		INSERT OR IGNORE INTO inventory (uid, item, qty)
		VALUES (424242, 'frog:pog:normal', 2)
		"""
    )
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "inventory consume",
            options={"slot": 1},
            user_id=424242,
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    press = await press_button(
        full_bot, custom_id=buttons["Yes"], message_id=555, user_id=424242
    )
    result = await task
    assert press.exceptions == [] and result.exceptions == []
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM member_exp_log WHERE uid = 424242"
        )
        == 1
    )
    contribs = await full_bot.effects.list(
        Scope.member(424242), FrogSeam.FROG_REACTION
    )
    assert len(contribs) == 1
    assert contribs[0].payload["chance"] == 0.01  # strongest value wins


async def test_consume_classy_via_driver_grants_role(
    full_bot: CazzuBot,
) -> None:
    """Classy consume adds the dev-guild role through the converger."""
    await full_bot.db.execute(
        """
		INSERT OR IGNORE INTO inventory (uid, item, qty)
		VALUES (424242, 'frog:classy:normal', 1)
		"""
    )
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "inventory consume",
            options={"slot": 1},
            user_id=424242,
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    press = await press_button(
        full_bot, custom_id=buttons["Yes"], message_id=555, user_id=424242
    )
    result = await task
    assert press.exceptions == [] and result.exceptions == []
    member = await full_bot.rest.fetch_member(
        full_bot.config.guild_id, 424242
    )
    assert _CLASSY_ROLE_DEV in {role.id for role in member.roles}
    # expiry: drive the converge job directly (the engine's dispatcher)
    from cazzubot.effects import EFFECT_CONVERGE_TAG

    payload = {
        "retry": True,
        "scope_kind": "member",
        "scope_id": 424242,
        "seam": FrogSeam.CLASSY_ROLE.key,
        "source": FrogEffect.CLASSY_ROLE.key,
    }
    await full_bot.scheduler.run_due()  # fire the scheduled converge job
    member = await full_bot.rest.fetch_member(
        full_bot.config.guild_id, 424242
    )
    assert _CLASSY_ROLE_DEV not in {role.id for role in member.roles}


async def test_capture_cluster_explodes_no_catchable_frog(
    full_bot: CazzuBot,
    monkeypatch,
) -> None:
    """/frog fake species=cluster bursts basics; no catchable frog message."""
    # seed text channels around 99 (the driver's default channel)
    from tests.fakes import FakeChannel

    gid = full_bot.config.guild_id
    guild = full_bot.rest.guilds[gid]
    for cid_, pos in ((98, 1), (99, 2), (100, 3)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        guild.channels[cid_] = channel
    # the burst fires background tasks — capture them without blocking
    spawned: list = []

    async def recording_spawn(
        b, persist, cid=None, species_key=None
    ) -> bool:
        spawned.append((cid, species_key))
        return False

    from plugins.frogs.effects import ClusterEffect

    original = ClusterEffect.spawn_impl
    ClusterEffect.spawn_impl = recording_spawn  # type: ignore[assignment]
    try:
        await run_slash(
            full_bot,
            "frog fake",
            options={"species": "cluster"},
            user_id=1,
            username="owner",
            timeout=10.0,
        )
    finally:
        ClusterEffect.spawn_impl = original
    # no catchable frog message was posted for the cluster itself
    assert not any(
        mid.startswith("frog:catch:") or "catch" in str(mid)
        for mid in rest_of(full_bot).created
    )
    assert 4 <= len(spawned) <= 10
    assert all(key == FrogItemKey.BASIC for _cid, key in spawned)
    assert all(cid_ in {98, 99, 100} for cid_, _key in spawned)
~~~~

1.  **Verify:**

~~~~ bash
uv run pytest tests/integration/test_frog_driver.py tests/plugins/frogs -q
uv run pytest -q
uv run ruff check . && uv run ruformat check .  # ruff format --check
uv run basedpyright
~~~~

Commit:
`git -c commit.gpgsign=false commit -m "feat(frogs): plugin wiring (converger, cleared-event revert, cluster spawn_impl) + driver e2e"`.


Task 9 — Docs + plan close-out
------------------------------

**Files:** `docs/PLUGINS.md`, `docs/SYSTEMS.md`,
`docs/needs-rewrite/ROADMAP.md`, `docs/needs-rewrite/EFFECTS.md`,
`docs/aegis/INDEX.md` (this plan),
`docs/aegis/baseline/2026-08-28-frog-species-baseline.md` (mark the
species table implemented if executed).

**Steps:**

1.  `docs/PLUGINS.md` — frogs plugin section: five species, the two seams
    (`FrogSeam.FROG_REACTION` internal / `CLASSY_ROLE` external +
    converger), the reactions listener, cluster spawn behavior, the
    `ClusterEffect.spawn_impl` injection note, and the ownership model
    (item composes; effects are generic scope-aware modifiers).
2.  `docs/SYSTEMS.md` — effects engine consumers list gains frogs
    (reaction + role seams).
3.  `docs/needs-rewrite/ROADMAP.md` — new “Phase 5 — FROG.md species”
    section summarizing this plan + implemented marker when done; roll the
    `still open` note (weights/rarity now resolved by FROG.md).
4.  `docs/needs-rewrite/EFFECTS.md` — spec update (owner decision
    2026-08-28): the Contribution section's `source` example is clarified
    to mean **the effect identity** — “re-publishing the same source” =
    “re-applying the same effect”, and several items that ARE the same
    effect (Pog/Froggers reaction) must publish under one shared source,
    with the item as payload provenance; add the feature-side value-merge
    pattern (strongest wins, window additive) as the example of an effect
    whose reapply policy is decided by its publisher. Also record the
    ownership model (owner 2026-08-28): the ITEM composes what consume
    does (exp + effect applications declared beside the item); the
    modifier registry is a generic, scope-aware primitive library any
    caller (item glue, admin command) can invoke — and note `ExpEffect`/
    `EXP` as vestigial (exp is item-owned behavior), to remove in a
    follow-up.
5.  `docs/aegis/INDEX.md` — append this plan. Final verify:

~~~~ bash
uv run pytest -q && uv run ruff check . && uv run basedpyright
hongdown -w docs/aegis docs/aegis/plans/2026-08-28-frog-species.md  # personal project
~~~~

Commit:
`git -c commit.gpgsign=false commit -m "docs(frogs): FROG.md species plan + plugin/system docs"`.


Verification (final, whole suite)
---------------------------------

~~~~ bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .   # plan code is written to match; format if it flags
uv run basedpyright
~~~~


Retirement
----------

 -  Rollback surface: each task is one commit; reverting restores the
    prior species set (code-only; no data migration). New inventory rows
    for pog/froggers/classy items are additive and harmless if reverted
    (consumers treat them as normal items on the new code only).
 -  Old owner/fallback: none — this adds, never replaces. `frog_exp`
    oracle extends; the `_SPECIES_EXP` dict is the only “legacy” value kept
    (basic 10/3).
 -  Deletion trigger: if a species is dropped, remove its `SPECIES` entry,
    its `FrogItems` members + exp rows, and (for cluster) its spawn payload
    — no table churn ever.


Execution Route
---------------

~~~~ text
Execution Route:
- Decision: inline
- Evidence: tasks share files heavily (species.py/effects.py/items.py/
  factory.py across Tasks 1–5) and follow one strict sequence; fan-out
  would fight the shared-file ordering and the RED/GREEN per task
- Fallback: subagent review of the final diff (receiving-code-review)
- User confirmation required: no — no irreversible or cross-boundary
  action; plan execution may begin after approval of this document
~~~~


Self-Review
-----------

 -  Spec coverage: every FROG.md species + rule has a task (D1–D11 carry
    the open values; EXTEND rule covered by the engine + Task 2 test).
 -  Placeholder scan: none — every task has complete code and commands.
 -  Type consistency: `EffectPayload` protocol used throughout; `Species`
    fields typed; `frog_item_key` single derivation; payloads frozen
    dataclasses.
 -  Compatibility: no schema change; CSR boundary preserved (effects.py
    hikari-free — channel-type check via the numeric constant); bare
    `Item` literals kept; `guild_listener` used.
 -  Change necessity: stated per task.
 -  Existence check: new surfaces are enum members + two module files;
    proof = task acceptance.
 -  Complexity: within budget; two new modules keep the graph acyclic.
 -  Architecture integrity: effects engine owns reapplication + converge;
    frogs only declare seams and pull (Lens above).
 -  Verification: exact commands per task + final suite.
