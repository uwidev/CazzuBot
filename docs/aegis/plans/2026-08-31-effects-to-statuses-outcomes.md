Rename “effects” → “statuses” and item “effects” → “outcomes”
=============================================================

Goal
----

Eliminate the generic noun **effect** from the project's major concepts.
Two renames, per the user's 2026-08-31 request (authority: user message

 -  `docs/ramblings.md`):

1.  **effects → statuses** — the generic, scope-aware persistent modifier
    *store* (module, service, table, seams) becomes **statuses**:
    “statuses are particular status effects applied to things — user
    status, frog spawn status, guild status”. A **status** is persistent
    scope-aware state recorded by the store.
2.  **effects → outcomes, for anything a thing *does*** — an **outcome**
    is the consequence of an action (consuming/activating an item,
    catching a frog, a spawn hook), and it *may invoke statuses* through
    `bot.statuses` — never the reverse. The frog species-side registry is
    an **outcome library** (`plugins/frogs/outcomes.py`), and items
    compose their own outcomes (`_SPECIES_OUTCOMES`) from it. Approved
    2026-08-31 with change: species-side behaviors are **outcomes**, not
    statuses (the original Cluster handler is an on-catch outcome, not an
    on-spawn status). The species-declares-outcomes refactor itself is a
    backlog item (D5/T8), not this turn.

Out of scope (generic-English or unrelated “effect” uses that stay):
lifecycle's *revertible/deferred effects* paper language
(`cazzubot/lifecycle.py`, plugin-lifecycle docs), “side effects”,
“take effect”, `effective_permissions`, `window.py` “outcome” prose.
These are not the named concepts.

The word **seam** is unchanged throughout (it was never ambiguous and was
not part of the request).


Architecture
------------

Two existing layers, renaming in place, plus one data migration:

| Layer                   | Today                                                     | After                                                     |
| ----------------------- | --------------------------------------------------------- | --------------------------------------------------------- |
| Core store module       | `cazzubot/effects.py`                                     | `cazzubot/statuses.py`                                    |
| Core service            | `Effects` / `bot.effects`                                 | `Statuses` / `bot.statuses`                               |
| Store row model         | `EffectContribution`                                      | `StatusContribution`                                      |
| Clear event             | `EffectsClearedEvent`                                     | `StatusesClearedEvent`                                    |
| Converge tag            | `EFFECT_CONVERGE_TAG` = `"effect.converge"`               | `STATUS_CONVERGE_TAG` = `"status.converge"`               |
| Store table             | `effect_contribution`                                     | `status_contribution` (migration 007)                     |
| Experience seams enum   | `EffectSeam`                                              | `StatusSeam`                                              |
| Frog outcome module    | `plugins/frogs/effects.py`                                | `plugins/frogs/outcomes.py`                               |
| Frog outcome enum      | `EffectKey`                                               | `OutcomeKey`                                              |
| Frog outcome protocols | `Effect` / `EffectPayload`                                | `Outcome` / `OutcomePayload`                              |
| Frog outcome handlers  | `ExpEffect` `ReactionEffect` `RoleEffect` `ClusterEffect` | `ExpOutcome` `ReactionOutcome` `RoleOutcome` `ClusterOutcome` |
| Frog identity enum     | `FrogEffect`                                              | `FrogStatus` (kept per D2; future: → outcomes)            |
| Species fields         | `catch_effect` / `spawn_effect`                           | `catch_outcome` / `spawn_outcome`                         |
| Item composition        | `_SPECIES_CONSUME`                                        | `_SPECIES_OUTCOMES`                                       |
| Docs spec               | `docs/needs-rewrite/EFFECTS.md`                           | `docs/needs-rewrite/STATUSES.md`                          |

Unchanged on purpose: `SeamKey`, `Scope`, `ScopeKind`, `ReapplyPolicy`,
`SCHEMA`, `FrogSeam`, `FrogState`, payload dataclasses' names
(`ReactionPayload`, `RolePayload`, `ClusterPayload`, `ExpPayload`), all
*stored strings* (seam keys `frog_reaction`/`classy_role`/
`message_exp_multiplier`, source identities `frog_reaction`/
`classy_role`/`legacy`, item ids `frog:<species>:<state>`, payload
fields) — **zero data re-keying**. Migration 007 only renames the table
and rewrites the converge tag string in `tasks`.


Tech Stack
----------

Python 3.14, hikari 2.5, hikari-lightbulb 3.2, aiosqlite, pendulum, uv
managed. Migration harness `scripts/migrate.py` +
`scripts/migrations/common.py`. Verification via `ruff`, `basedpyright`,
`pytest`.


Baseline / Authority Refs
-------------------------

 -  Authority: user request (2026-08-31) + `docs/ramblings.md`
    (“outcome? consuming an item results in this outcome. that could
    work.” / “rename ‘effects’ to ‘status’”).
 -  Baseline: `docs/aegis/baseline/2026-08-28-frog-species-baseline.md`
    (historical record — **not** edited; terminology there stays as
    measured).
 -  Related refs: `docs/needs-rewrite/EFFECTS.md` (the store spec, gets
    renamed + reworded), `docs/FROG.md`, `docs/needs-rewrite/PLUGINS.md`,
    `docs/SYSTEMS.md` (live docs updated in place).
 -  Historical records deliberately untouched: `docs/aegis/plans/*`,
    `docs/needs-rewrite/{ROADMAP,DONE,HANDOFF_ITEMS,ITEMS,INVENTORY, ARCHITECTURE,ASSETS,PLUGIN_ARCHITECTURE,MIGRATION,TESTING,BACKLOG, HIKARI_MIGRATION}.md`,
    `docs/PLAN_DB_MODELS.md`, migration 006 module and its wrapper
    `scripts/migrate_effect_contributions.py` (they describe/run the past
    shape).


Compatibility Boundary
----------------------

 -  **DB**: the boot-time schema guard (`db.verify_schema`) compares the
    Python DDL exactly. After T1 the code declares `status_contribution`;
    any DB still holding `effect_contribution` refuses to boot. Migration
    `007_status_contribution` renames the table and rewrites
    `tasks.tag = 'effect.converge'` → `'status.converge'` (in-flight
    convergence jobs survive). Must run on dev DB in this workstream; prod
    DB stays pending (bot stopped) — deploy-time, user-authorized.
 -  **Stored strings**: seam keys, contribution sources, item ids, payload
    JSON — all unchanged. No data migration of row values.
 -  **Python API**: `bot.effects` → `bot.statuses` etc. Internal-only
    (plugins are in-repo; no external consumers).
 -  **User-facing text**: `/inventory consume` description
    “for its effect” → “for its outcome” (cosmetic; syncs on boot).


TDD Route
---------

~~~~ text
TDD Route:
- Mode: off
- Decision: skipped
- Strict authority: not applicable
- Strict signals: none (pure rename — no behavior change)
- Reason: mechanical symbol/module rename; every behavior is pinned by
  the existing suite (684 tests). New migration 007 gets a focused
  post-change test (needs/plan/migrate/verify on a temp DB), not a RED
  cycle.
- Verification: full `pytest` + ruff + basedpyright after each slice.
~~~~


Verification (overall)
----------------------

~~~~ bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run pytest
~~~~

Each task below lists its focused command; T9 runs everything.


Scope Check
-----------

~~~~ text
Requirement Ready Check:
- Requirement source refs: user message (2026-08-31); docs/ramblings.md
- Goals and scope refs: two renames above; out-of-scope list
- Acceptance / verification criteria refs: no "effect" remains as a
  concept name in live code/docs; full suite green; dev DB migrated
- Open blocker questions: none (see Decisions for the two flagged calls)
- Decision: ready
~~~~

~~~~ text
Change Necessity:
- User-visible need: project terminology hygiene — "effect" is a
  catch-all; statuses/outcomes isolate the concepts
- No-change / non-code option: docs-only would leave symbols, the DB
  table and the service named "effects" — the confusion persists
- Why code change is necessary: the concept names live in modules,
  classes, an enum registry, a DB table and a scheduler tag
- Minimum change boundary: the rename map table above (no behavior
  changes, no refactors beyond renames)
- Decision: code-change
~~~~

~~~~ text
Existence Check:
- Proposed new surface: `docs/CONTEXT.md` (canonical terminology file,
  per establishing-project-context — first resolved domain terms)
- Existing owner / reuse candidate: none exists (no CONTEXT.md today)
- Why existing surface is insufficient: n/a — new glossary owner
- Creation proof: user's rename is an A-grade directive; skill requires
  the file on the first resolved term
- Entropy / retirement impact: low; one small file
- Decision: add-with-proof
~~~~

~~~~ text
Architecture Integrity Lens:
- Invariant: the status store stays the single owner of persistence,
  reapply policy and convergence; items and species compose outcomes;
  outcomes invoke statuses (owner 2026-08-28 "the item composes, effects
  modify" — now "the item composes, outcomes invoke"); the species →
  outcomes import edge stays one-way
- Canonical owner / contract: `bot.statuses` (timed + external seams)
- Responsibility overlap: none introduced — pure renames
- Falsifier: any renamed symbol whose behavior changed → caught by suite
- Verdict: proceed
~~~~

~~~~ text
Plan Pressure Test:
- Owner / contract / retirement: migration 007 owns the table rename;
  Converger/RoleConverger contracts unchanged
- Architecture integrity: no higher-level path missed (seam stays a
  distinct concept; lifecycle effects explicitly out of scope)
- Verification scope: full suite + boundary tests (CSR/DB lists updated)
- Task executability: bite-sized, exact maps below
- Pressure result: proceed
~~~~

~~~~ text
Complexity Budget:
- Artifact class: mechanical cross-tree rename + one data migration
- Target files: ~55 files (30 py, ~7 tests, ~6 docs, CONTEXT.md, 2 new)
- Current pressure: low (effects.py 684 lines, statuses.py after rename
  identical shape)
- Projected post-change pressure: unchanged (same code, new names)
- Budget result: within-budget
- Planned governance: one commit per task, full suite between tasks
~~~~


File Map
--------

| Task | Files                                                                                                                                                             | Kind                |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- |
| T1   | `cazzubot/effects.py`→`statuses.py`, `__init__.py`, `bot.py`, `db.py`, `scheduler.py`                                                                             | core store + wiring |
| T2   | `plugins/experience/logic.py`, `plugins/inventory/extension.py`, `cazzubot/inventory.py`, `cazzubot/items.py`                                                     | consumers + prose   |
| T3   | `plugins/frogs/effects.py`→`outcomes.py`, `seams.py`, `species.py`, `items.py`, `factory.py`, `extension.py`, `reactions.py`, `events.py`, `db.py`, `__init__.py` | frog outcome slice |
| T4   | 13 test files (renames + reference updates)                                                                                                                       | tests               |
| T5   | `scripts/migrations/status_contribution.py` (new), `scripts/migrations/__init__.py`, 2 test files                                                                 | migration 007       |
| T6   | `docs/SYSTEMS.md`, `docs/needs-rewrite/PLUGINS.md`, `docs/needs-rewrite/EFFECTS.md`→`STATUSES.md`, `docs/FROG.md`, 2 `docs/how-do-i/*.md`                         | docs                |
| T7   | `CONTEXT.md` (new)                                                                                                                                                | glossary            |
| T8   | `docs/needs-rewrite/BACKLOG.md` (append: species compose outcomes)                                                                                                | backlog             |
| T9   | dev DB (migration apply), full verify, commits                                                                                                                    | integration         |


Tasks
-----

### T1 — Core store rename + wiring

**Files:**

 -  `cazzubot/effects.py` → `cazzubot/statuses.py` (`mv`)
 -  `cazzubot/__init__.py`
 -  `cazzubot/bot.py`
 -  `cazzubot/db.py` (docstring line 11 list)
 -  `cazzubot/scheduler.py` (docstring line 22 tag ref)

**Why:** the store *is* the “effects” concept the user wants called
statuses. **Change Necessity:** the concept name lives in the module,
class, table, event and tag. **Impact/Compatibility:** boot guard
requires migration 007 before the renamed DDL boots; stored strings
unchanged. **Verification:** `uv run pytest tests/core/test_effects.py -q`
after T4 lands (interim: `python -c "import cazzubot.statuses"`).

**Steps:**

1.  `mv cazzubot/effects.py cazzubot/statuses.py`; `mv cazzubot/../../` no —
    `git mv` not needed, plain `mv` + later `git add -A`.
2.  In `cazzubot/statuses.py` rename (symbol → symbol, all occurrences,
    docstrings rewritten to statuses language):
     -  `Effects` → `Statuses`; docstring “The effects service on the bot
        (`bot.effects`)” → “The statuses service on the bot
        (`bot.statuses`)”
     -  `EffectContribution` → `StatusContribution` (+ its one-line comment)
     -  `EffectsClearedEvent` → `StatusesClearedEvent` (class + all docstring
        refs; “External effect rows” → “External status rows”)
     -  `EFFECT_CONVERGE_TAG` → `STATUS_CONVERGE_TAG`; value
        `"effect.converge"` → `"status.converge"` (constant + scheduler
        register + `add` calls + `_on_converge_due` docstring)
     -  Table name in `_SCHEMA` DDL: `effect_contribution` →
        `status_contribution` (SQL in publish/list/fetch/clear/clear\_scope
        too — 8 statements)
     -  Module docstring: “Effects seam store” → “Statuses seam store”; the
        “Naming note” paragraph (line 24–26) becomes: the core module is the
        *persistent status store*; `plugins/frogs/outcomes.py` is the
        species-side *instant catch/consume outcome library*; outcomes may
        **invoke statuses** (never the reverse); an item's consume composes
        its own **outcome** from that library.
     -  `docs/needs-rewrite/EFFECTS.md` refs → `STATUSES.md`
3.  `cazzubot/__init__.py`: `from cazzubot.effects import Effects` →
    `from cazzubot.statuses import Statuses`; export list `"Effects"` →
    `"Statuses"`.
4.  `cazzubot/bot.py`: import `Effects` → `Statuses` from
    `cazzubot.statuses`; `self.effects = Effects(self)` →
    `self.statuses = Statuses(self)`; the two schema-list spots
    (`self.effects.schema` → `self.statuses.schema`).
5.  `cazzubot/db.py`: docstring “(settings, scheduler, assets, inventory,
    effects)” → “(…, statuses)”.
6.  `cazzubot/scheduler.py`: docstring “`effects` (the `effect.converge`
    tag)” → “`statuses` (the `status.converge` tag)”.
7.  Verify: `uv run ruff check cazzubot && uv run basedpyright`.

### T2 — Experience consumer + inventory/items prose

**Files:** `plugins/experience/logic.py`, `plugins/inventory/extension.py`,
`cazzubot/inventory.py`, `cazzubot/items.py`.

**Why:** experience is the first status pull (`award_exp`); the inventory
UI text says “effect” to users. **Verification:**
`uv run pytest tests/plugins/experience/test_on_message.py -q`.

**Steps:**

1.  `plugins/experience/logic.py`:
     -  imports: `from cazzubot import effects, levels` →
        `from cazzubot import statuses, levels`;
        `from cazzubot.effects import Scope` →
        `from cazzubot.statuses import Scope`
     -  `EffectSeam` → `StatusSeam` (class + “Experience's seams — typed
        keys… (see `cazzubot/statuses.py`)”)
     -  `await effects.product(...)` → `await statuses.product(...)`
2.  `plugins/inventory/extension.py`:
     -  consume description: “for its effect.” → “for its outcome.”
     -  docstring “the item's own effect” → “the item's own outcome”;
        comment “a failed effect never eats items” → “a failed outcome
        never eats items”
3.  `cazzubot/inventory.py` docstring (line 8): “Item *definitions* (what
    an item is, its effects, art)” → “(…, its outcomes, art)”; line 7
    “the asset\_key / EffectKey pattern” → “the asset\_key / StatusKey
    pattern”.
4.  `cazzubot/items.py` docstring (line 12): “(spawn cadence, catch
    effect)” → “(spawn cadence, catch status)”.
5.  Verify:
    `uv run ruff check plugins/experience plugins/inventory cazzubot/inventory.py cazzubot/items.py`.

### T3 — Frog slice (registry, seams, species, items, flow)

**Files:**

 -  `plugins/frogs/effects.py` → `plugins/frogs/outcomes.py` (`mv`)
 -  `plugins/frogs/seams.py`, `species.py`, `items.py`, `factory.py`,
    `extension.py`, `reactions.py`, `events.py`, `db.py`, `__init__.py`

**Why:** the frog species-side registry is where “effects” meant *what a
frog does* — per the approved D1, that is the **outcome library**
(outcomes may invoke statuses, never the reverse); the item composition
is where “effects” becomes “outcomes”. **Verification:**
`uv run pytest tests/plugins/frogs -q` (with T4).

**Steps:**

1.  `mv plugins/frogs/effects.py plugins/frogs/outcomes.py`. In
    `plugins/frogs/outcomes.py` (the species-side **outcome library** —
    outcomes may invoke statuses, never the reverse; D1 approved
    2026-08-31):
     -  module docstring: “Frog species effects — a typed, payload-driven
        effect registry” → “Frog species outcomes — a typed,
        payload-driven outcome library”; “each effect owns” → “each
        outcome owns”; “consume modifiers are generic scope-aware
        primitives (owner 2026-08-28)” keeps the meaning but rewords to
        “outcomes are generic, scope-aware: each may invoke statuses via
        `bot.statuses` (or act directly), and the item's consume
        composition today (`items.py::_SPECIES_OUTCOMES`) composes
        them”; `docs/needs-rewrite/EFFECTS.md` → `STATUSES.md`
     -  `EffectPayload` → `OutcomePayload` (protocol; docstring “A
        species-side outcome configuration”)
     -  `Effect` → `Outcome` (protocol; “One species outcome: optional
        catch hook, optional consume hook”; consume hook docstring “An
        outcome takes a **Scope**…”)
     -  `ExpEffect` → `ExpOutcome`; `ReactionEffect` → `ReactionOutcome`;
        `RoleEffect` → `RoleOutcome`; `ClusterEffect` → `ClusterOutcome`
        (class names + every internal reference/docstring; error strings
        “exp effect requires ExpPayload” → “exp outcome requires
        ExpPayload”, etc.)
     -  `EffectKey` → `OutcomeKey` (enum + “The outcome library — each
        member's value IS its handler”)
     -  `RoleConverger` docstrings: “the CLASSY\_ROLE seam… Registered via
        `bot.statuses.register_converger`“; the converger converges a
        **status** (the classy-role contribution); reason string “classy
        frog role effect” → “classy frog role status”
     -  import `from cazzubot.effects import …` →
        `from cazzubot.statuses import …`
2.  `plugins/frogs/seams.py`:
     -  module docstring “Frog effect seams” → “Frog status seams”; “Frogs'
        input points on the effects engine” → “… statuses engine”;
        “plugins/frogs/effects.py::RoleConverger” → “plugins/frogs/
        outcomes.py::RoleConverger”
     -  `FrogEffect` → `FrogStatus` (“Frog status identities — the `source`
        of a contribution”; “The same status is keyed by (scope, seam,
        source)”) — kept per D2 with the future intention of moving the
        identity concept to outcomes when species-level outcome
        composition lands.
3.  `plugins/frogs/species.py`:
     -  import `from .effects import ClusterPayload, EffectPayload` →
        `from .outcomes import ClusterPayload, OutcomePayload`
     -  fields: `catch_effect: EffectPayload | None` →
        `catch_outcome: OutcomePayload | None`; `spawn_effect` →
        `spawn_outcome`; SPECIES entries' keywords renamed likewise
     -  docstrings: “Effects are referenced by payload instance… (see
        `outcomes.py`)”; “the item composes, effects modify” → “the item
        composes, outcomes invoke”; “`catch_outcome` handles the catch
        side; `spawn_outcome` replaces the catchable frog at spawn time
        (Cluster's explosion)”
4.  `plugins/frogs/items.py`:
     -  imports:
        `from .effects import EffectPayload, ReactionPayload, RolePayload` →
        `from .outcomes import OutcomePayload, ReactionPayload, RolePayload`
     -  `_SPECIES_CONSUME` → `_SPECIES_OUTCOMES` (definition + `classy_role_ids`
        iteration + `_consume_item` + `_consume_blurb` + comments)
     -  docstrings: “composes the state-modifying effects it applies
        (`_SPECIES_CONSUME`…)” → “composes the outcomes it produces:
        exp + the outcome applications it composes (`_SPECIES_OUTCOMES`…
        Basic composes none; Pog/Froggers the reaction outcome, Classy
        the role outcome). Outcomes are generic, scope-aware primitives
        that may invoke statuses (`outcomes.py`)”; “the item composes,
        effects modify” → “the item composes, outcomes invoke”; “composed
        effect applications” → “composed outcome applications”; “The
        composed effect applications (`_SPECIES_CONSUME`) then run as
        generic scope-aware modifiers” → “The composed outcome
        applications (`_SPECIES_OUTCOMES`) then run as generic
        scope-aware outcomes”
     -  `frog_item_key` docstring (in outcomes.py): “a consume effect's
        seam `source`“ → “a consume outcome's status `source`“
5.  `plugins/frogs/factory.py`: `species.spawn_effect` →
    `species.spawn_outcome` (3 sites); `species.catch_effect` →
    `species.catch_outcome` (2 sites); comments “spawn-effect species” →
    “spawn-outcome species”; “custom catch effect owns whatever it grants”
    → “custom catch outcome owns…”.
6.  `plugins/frogs/extension.py`: `species.spawn_effect` →
    `species.spawn_outcome` (catalog branch).
7.  `plugins/frogs/reactions.py`: docstring “the reaction effect is keyed
    by effect identity” → “the reaction status is keyed by status
    identity” (the reaction *outcome* publishes a status; this listener
    reads the status); `bot.effects.list` → `bot.statuses.list`; import
    stays `from cazzubot.statuses import Scope`.
8.  `plugins/frogs/events.py`: `FrogCapturedEvent` docstring “catch effect
    ran” → “catch outcome ran”; `FrogConsumedEvent` “effect ran” →
    “outcome ran”.
9.  `plugins/frogs/db.py`: `from .effects import frog_item_key` →
    `from .outcomes import frog_item_key`.
10. `plugins/frogs/__init__.py`:
     -  `from cazzubot.effects import EffectsClearedEvent, ScopeKind` →
        `from cazzubot.statuses import ScopeKind, StatusesClearedEvent`
     -  `from .effects import EffectKey, RoleConverger` →
        `from .outcomes import OutcomeKey, RoleConverger`
     -  `EffectKey.CLUSTER.value.spawn_impl = …` →
        `OutcomeKey.CLUSTER.value.spawn_impl = …` (both load/unload spots)
     -  `bot.effects.register_converger` / `bot.effects.unregister_converger`
        → `bot.statuses.…`
     -  `EffectsClearedEvent` → `StatusesClearedEvent` (subscribe + handler
        signature); `_on_effects_cleared` → `_on_statuses_cleared`;
        comment “the effects-cleared revert” → “the statuses-cleared
        revert”.
11. Verify: `uv run ruff check plugins/frogs && uv run basedpyright`.

### T4 — Tests

**Files:**

 -  `tests/core/test_effects.py` → `tests/core/test_statuses.py` (`mv`)
 -  `tests/core/test_member_effects.py`
 -  `tests/core/test_csr_boundary.py`
 -  `tests/core/test_db_boundary.py`
 -  `tests/core/test_migrate_effect_contributions.py`
 -  `tests/plugins/frogs/test_effects.py` →
    `tests/plugins/frogs/ test_outcomes.py` (`mv`)
 -  `tests/plugins/frogs/test_items.py`
 -  `tests/plugins/frogs/test_species.py`
 -  `tests/plugins/frogs/test_cluster.py`
 -  `tests/plugins/frogs/test_reactions.py`
 -  `tests/integration/test_frog_driver.py`
 -  `tests/plugins/experience/test_on_message.py`

**Why:** tests carry the old symbol names; the CSR/DB boundary tests hardcode
module filenames. **Verification:**
`uv run pytest tests/core tests/plugins tests/integration -q`.

**Steps:**

1.  `mv tests/core/test_effects.py tests/core/test_statuses.py`:
     -  imports `from cazzubot import effects` →
        `from cazzubot import statuses` (module-level + the
        `import cazzubot.effects as`-style),
        `from cazzubot.effects import (EFFECT_CONVERGE_TAG, …)` →
        `from cazzubot.statuses import (STATUS_CONVERGE_TAG, …)`; `Effects` →
        `Statuses` everywhere (`bot.effects` → `bot.statuses`);
        `effect_contribution` in SQL strings → `status_contribution`; fixture
        `effects_db` → `statuses_db`; module/function docstrings (e.g.
        “External seam… Effects.publish” → “Statuses.publish”).
2.  `tests/core/test_member_effects.py`: module docstring store ref
    `cazzubot/effects.py` → `cazzubot/statuses.py`; imports
    `from cazzubot import effects` → `statuses` and
    `from cazzubot.effects import ReapplyPolicy, SCHEMA, Scope` →
    `from cazzubot.statuses import …`; `effects.` call sites → `statuses.`;
    fixture docstring “carrying the effect\_contribution schema” → “the
    status\_contribution schema”.
3.  `tests/core/test_csr_boundary.py`: `SERVICE_FILENAMES` tuple:
    `"effects.py"` → `"outcomes.py"`.
4.  `tests/core/test_db_boundary.py`: `_TABLE_OWNERS`:
    `"cazzubot/effects.py"` → `"cazzubot/statuses.py"`.
5.  `tests/core/test_migrate_effect_contributions.py` (tests 006 — the
    legacy fold): keep every 006 assertion (`effect_contribution` after
    006, `member_effect` gone) — 006 is history and still writes
    `effect_contribution`; only the tail that exercises the *current*
    store API changes: `from cazzubot import effects` →
    `from cazzubot import statuses`; `await effects.product(...)` →
    `await statuses.product(...)`.
6.  `mv tests/plugins/frogs/test_effects.py tests/plugins/frogs/ test_outcomes.py`:
    imports `from cazzubot.effects import Scope` →
    `from cazzubot.statuses import Scope`;
    `from plugins.frogs.effects import (…EffectKey, ExpPayload…)` →
    `from plugins.frogs.outcomes import (…OutcomeKey, …)`; `EffectKey.` →
    `OutcomeKey.`; docstrings/ test names (“effect key” → “outcome key”,
    “exp effect” → “exp outcome”, “spawn\_effect” → “spawn\_outcome”).
7.  `tests/plugins/frogs/test_items.py`: imports; `_SPECIES_CONSUME` →
    `_SPECIES_OUTCOMES`; test name `test_consume_composes_item_effects` →
    `test_consume_composes_item_outcomes`; docstring “item's composed
    reaction effect” → “item's composed reaction outcome”; “Production
    has no composed effect for Basic” → “no composed outcome for Basic”.
8.  `tests/plugins/frogs/test_species.py`: `cluster.spawn_effect` →
    `cluster.spawn_outcome`; `assert not hasattr(basic, "consume_effect")`
    → `assert not hasattr(basic, "consume_outcome")`.
9.  `tests/plugins/frogs/test_cluster.py`:
    `from plugins.frogs.effects import ClusterEffect, ClusterPayload` →
    `from plugins.frogs.outcomes import ClusterOutcome, ClusterPayload`;
    `effect = ClusterEffect()` → `outcome = ClusterOutcome()` (variable +
    uses); `"plugins.frogs.effects. random"` → `"plugins.frogs.outcomes.
    random"` in the monkeypatch.
10. `tests/plugins/frogs/test_reactions.py`: `bot.effects.publish` →
    `bot.statuses.publish`.
11. `tests/integration/test_frog_driver.py`:
    `from cazzubot.effects import EFFECT_CONVERGE_TAG, Scope` →
    `from cazzubot.statuses import ( STATUS_CONVERGE_TAG, Scope)`;
    `full_bot.effects.list` → `full_bot.statuses.list`;
    `from plugins.frogs.effects import EffectKey` →
    `from plugins.frogs.outcomes import OutcomeKey`.
12. `tests/plugins/experience/test_on_message.py`:
    `from cazzubot import effects` → `statuses`;
    `from cazzubot.effects import Scope` →
    `from cazzubot.statuses import Scope`; `EffectSeam` → `StatusSeam`.
13. Verify: `uv run pytest tests/core tests/plugins tests/integration -q`.

### T5 — Migration 007 (table + tag rename)

**Files:**

 -  `scripts/migrations/status_contribution.py` (new)
 -  `scripts/migrations/__init__.py`
 -  `tests/core/test_migration_runner.py`
 -  `tests/core/test_migrate_status_contribution.py` (new)

**Why:** the boot guard makes the table name part of the public contract;
the tag string lives in scheduler rows. **Verification:**
`uv run pytest tests/core/test_migration_runner.py tests/core/ test_migrate_status_contribution.py -q`

 -  dry-run against a copy of the dev DB.

**Steps:**

1.  Create `scripts/migrations/status_contribution.py`:

~~~~ python
"""Migration: rename the effects store to statuses.

Part of the 2026-08-31 terminology rename: the generic persistent
modifier store is now **statuses** (``cazzubot/statuses.py``,
``bot.statuses``). This migration renames the store's table
``effect_contribution`` —> ``status_contribution`` (no column or value
changes: scope_kind/scope_id/seam/source/payload/expires_at and every
stored seam/source string stay byte-identical) and rewrites the
scheduler's convergence tag ``effect.converge`` —> ``status.converge``
(a ``tasks`` projection update, idempotent for rows that already fired).

Idempotent: ``needs_migration`` is False once ``effect_contribution`` is
gone. Run through ``scripts/migrate.py`` (all pending) or
``--only 007_status_contribution``; dry-run by default, ``--commit`` to
write, backup before mutation, bot stopped.
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """What the migration found — the dry-run report."""

    tables: int  # effect_contribution tables to rename (0 or 1)
    converger_rows: int  # tasks rows still tagged effect.converge


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True while the legacy ``effect_contribution`` table is present."""
    return "effect_contribution" in _table_names(conn)


def plan(conn: sqlite3.Connection) -> MigrationPlan:
    """Read-only report of what :func:`migrate` would rename."""
    (rows,) = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE tag = 'effect.converge'"
    ).fetchone()
    return MigrationPlan(
        tables=1 if "effect_contribution" in _table_names(conn) else 0,
        converger_rows=rows,
    )


def migrate(conn: sqlite3.Connection) -> MigrationPlan:
    """Apply in one transaction; returns what it did.

    ``ALTER TABLE ... RENAME`` preserves row data, the PK and indexes;
    no FK references the table. The tag rewrite touches only the
    scheduler's ``tasks`` projection for the status store's converge
    jobs, leaving every other tag untouched.
    """
    before = plan(conn)
    conn.execute("BEGIN")
    try:
        if "effect_contribution" in _table_names(conn):
            conn.execute(
                "ALTER TABLE effect_contribution RENAME TO"
                + " status_contribution"
            )
        conn.execute(
            "UPDATE tasks SET tag = 'status.converge'"
            + " WHERE tag = 'effect.converge'"
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


def verify(conn: sqlite3.Connection) -> None:
    """Post-commit checks: the rename landed and no stale tag remains."""
    tables = _table_names(conn)
    assert "effect_contribution" not in tables, "legacy table not renamed"
    assert "status_contribution" in tables, "status_contribution missing"
    (rows,) = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE tag = 'effect.converge'"
    ).fetchone()
    assert rows == 0, "stale effect.converge task rows remain"


MIGRATION = Migration(
    id="007_status_contribution",
    doc="rename effect_contribution -> status_contribution + converge tag",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        f"rename {p.tables} table(s), re-tag {p.converger_rows} task"
        + " row(s)"
    ),
    migrate=migrate,
    verify=verify,
)
~~~~

1.  `scripts/migrations/__init__.py`: import `status_contribution`; append
    `status_contribution.MIGRATION` to `MIGRATIONS` after
    `effect_contributions.MIGRATION` (006 order must precede 007; on prod
    both run in order).
2.  `tests/core/test_migration_runner.py`: extend the expected ids list in
    `test_registry_is_ordered_and_ids_unique` with
    `"007_status_contribution"`.
3.  Create `tests/core/test_migrate_status_contribution.py` (complete):

~~~~ python
"""Status-contribution migration — effect_contribution -> status_contribution.

Builds a temp DB shaped like the post-006 store (``effect_contribution``
plus a live converge task row), then drives ``needs_migration`` /
``plan`` / ``migrate`` / ``verify``; asserts the table rename preserves
rows and the tag rewrite lands. A fresh DB is skipped (idempotence gate).
"""

from __future__ import annotations

import sqlite3

from scripts.migrations.status_contribution import (
    MIGRATION,
    migrate,
    needs_migration,
    plan,
    verify,
)

SCHEMA = """
CREATE TABLE effect_contribution (
    scope_kind TEXT NOT NULL,
    scope_id   INTEGER NOT NULL,
    seam       TEXT NOT NULL,
    source     TEXT NOT NULL,
    payload    TEXT NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (scope_kind, scope_id, seam, source)
)
"""


def _conn(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        SCHEMA
        + """
        CREATE TABLE tasks (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            tag     TEXT NOT NULL,
            run_at  TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks (run_at);
        """
    )
    return conn


def test_needs_gate_is_fresh_db_skipped(tmp_path) -> None:
    conn = _conn(tmp_path / "fresh.db")
    try:
        assert needs_migration(conn) is False
    finally:
        conn.close()


def test_migrate_renames_table_and_rewrites_tag(tmp_path) -> None:
    conn = _conn(tmp_path / "live.db")
    try:
        conn.execute(
            "INSERT INTO effect_contribution VALUES"
            " ('member', 1, 'classy_role', 'classy_role', '{}', NULL)"
        )
        conn.execute(
            "INSERT INTO tasks VALUES"
            " ('effect.converge', '2026-01-01T00:00:00+00:00', '{}')"
        )
        conn.commit()

        assert needs_migration(conn) is True
        assert plan(conn).converger_rows == 1
        migrate(conn)
        verify(conn)

        row = conn.execute("SELECT * FROM status_contribution").fetchone()
        assert (row["scope_kind"], row["source"]) == (
            "member",
            "classy_role",
        )
        (tags,) = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE tag = 'status.converge'"
        ).fetchone()
        assert tags == 1
    finally:
        conn.close()
~~~~

1.  Dry-run against a copy of the dev DB:
    `cp data/cazzubot-dev.db /tmp/dev-pre007.db && uv run python scripts/migrate.py --db /tmp/dev-pre007.db --only 007_status_contribution`
    (expect the plan line; no write).
2.  Verify:
    `uv run pytest tests/core/test_migration_runner.py tests/core/ test_migrate_status_contribution.py -q && uv run ruff check scripts`.

### T6 — Docs

**Files:** `docs/SYSTEMS.md`, `docs/needs-rewrite/PLUGINS.md`,
`docs/needs-rewrite/EFFECTS.md` → `docs/needs-rewrite/STATUSES.md`,
`docs/FROG.md`, `docs/how-do-i/add-a-frog-species.md`,
`docs/how-do-i/grant-consume-items.md`.

**Why:** live docs describe the concepts by the old names. **Verification:**
read-through; `grep -rn 'effect' docs/SYSTEMS.md` returns only
generic-English uses.

**Steps:**

1.  `docs/SYSTEMS.md`:
     -  “### Effects — `cazzubot/effects.py`“ → “### Statuses —
        `cazzubot/statuses.py`“; “What: Scope-aware contribution store +
        convergence jobs” → “What: Scope-aware status store + convergence
        jobs”
     -  Scheduler “Used by: bot (tags), effects (converge)” → “statuses
        (converge)”
     -  Scheduled-tags list: `effect.converge` — effects — external-seam
        convergence → `status.converge` — statuses — external-seam
        convergence
     -  Key flows “**Effects:**“ → ”**Statuses:**“; “pulls the message-exp
        multiplier (`EffectSeam`)” → “(`StatusSeam`)”; “revert via
        `effect.converge`“ → ”`status.converge`“
2.  `docs/needs-rewrite/PLUGINS.md`:
     -  `bot.effects` — the **seam / contribution store** → `bot. statuses` —
        the **status store**; “**Ownership (2026-08-28): the ITEM composes,
        effects modify**“ → “the ITEM composes, outcomes invoke statuses”;
        “applies the modifiers it declares; the modifier registry
        (`plugins/frogs/effects.py::EffectKey`)” →
        “(`plugins/frogs/outcomes.py::OutcomeKey`)”; “`ClusterEffect`,
        `spawn_impl` injected at load — the edge `effects → factory`“ →
        “`ClusterOutcome`… the edge `outcomes → factory`“; “`EffectKey.EXP`
        stays as the vestigial pre-composition fossil” → “`OutcomeKey.EXP`“;
        ”`EffectsClearedEvent` reverts instantly” → “`StatusesClearedEvent`“
     -  Consume/effect payload section (Cluster): “a catch effect, and an
        optional **spawn effect**“ → “a catch outcome, and an optional
        **spawn outcome**“; ”`Species.spawn_effect` short-circuits” →
        “`spawn_outcome`“; ”**Lifecycle — declare your undos.** Every
        runtime effect” — generic-English, keep.
3.  `mv docs/needs-rewrite/EFFECTS.md docs/needs-rewrite/STATUSES.md`;
    content: title “Effects Seam Store” → “Statuses Seam Store”; “persistent
    effects” → “persistent statuses”; “member effects” →
    “member statuses” (in prose), legacy `member_effect` store
    references stay (history); “effects engine” → “statuses engine”;
    “Contribution —… (**the effect identity**…)” → “StatusContribution —
    … (**the status identity**…)”; “the identity of ‘the same effect’”
    → “‘the same status’”; “EffectsClearedEvent” → “StatusesClearedEvent”;
    “`cazzubot/effects.py`“ → ”`cazzubot/statuses.py`“.
4.  `docs/FROG.md` light pass (concept only; requirements prose keeps plain
    language): “and their effects” → “and their statuses”; “when an
    effect is ongoing, only the duration is increased, not for a
    stronger effect” → “when a status is ongoing… not for a stronger
    status”; “reapply an effect that already exists on a user” →
    “reapply a status…”; “user effects, but to any effect. Effects might
    apply to something like…” — reword to “user statuses, but to any
    status. Statuses might apply to…”. (No symbol names in FROG.md.)
5.  `docs/how-do-i/add-a-frog-species.md`:
    `catch_effect=None, # default catch: +1 to inventory` →
    `catch_outcome=None, …`; the two `catch_effect` prose bullets →
    `catch_outcome`; “To give it a custom effect, see
    `plugins/frogs/effects.py`“ → “To give it a custom outcome, see
    `plugins/frogs/outcomes.py`“.
6.  `docs/how-do-i/grant-consume-items.md`: “To attach an effect (e.g.
    granting exp)” → “To attach an outcome (e.g. granting exp)”.
7.  Verify:
    `grep -rn 'bot\.effects\|EffectKey\|EffectSeam\|_SPECIES_CONSUME' docs/ | grep -v needs-rewrite/ROADMAP`
    (expect only historical files).

### T7 — CONTEXT.md

**Files:** `CONTEXT.md` (new, project root).

**Why:** this rename resolves the project's first ambiguous domain terms
(“effect” meant both the status store and entity/item behavior); per
establishing-project-context, an A-grade directive writes the canonical
glossary. **Verification:** read-through; terms match the rename map.

**Steps:** create `CONTEXT.md`:

~~~~ markdown
# Project Context — CazzuBot

## Canonical terms

  -  **status** (plural **statuses**) — persistent, scope-aware state
     applied to a scope: a contribution recorded against a member or the
     guild (user status, guild status, frog spawn status). Canonical
     owner of the concept: the status store (`cazzubot/statuses.py`,
     `bot.statuses`).
  -  **outcome** — the consequence of an action (consuming an item,
     catching a frog, a spawn hook). An outcome *may invoke statuses*,
     never the reverse — that is the boundary. Items compose their own
     outcomes (`_SPECIES_OUTCOMES`); the frog species-side outcome
     library is `plugins/frogs/outcomes.py::OutcomeKey`. (Species
     themselves composing outcomes like items do is a backlog item —
     see docs/aegis/plans/2026-08-31-effects-to-statuses-outcomes.md D5.)
  -  **seam** — a feature-declared input point on its own calculator;
     typed seams (`SeamKey`) address the status store. Unchanged by the
     2026-08-31 rename.

## Avoided aliases / overloaded names

  -  **effect / effects** — retired 2026-08-31 as a concept name; it was a
     catch-all (visual effects, cause-and-effect, side effects). Live
     generic-English uses ("side effects", "take effect") are not
     concepts.

## Relationships

  -  an item **composes** its **outcome**; an outcome **invokes**
     **statuses** through the status store
  -  a status is **applied to** a Scope (member or guild) and **pulled**
     by the feature that owns its seam
~~~~

### T8 — Backlog entry (species compose outcomes)

**Files:** `docs/needs-rewrite/BACKLOG.md` (append).

**Why:** the user explicitly directed this follow-up to the backlog
(2026-08-31 approval): frog species should operate like items — compose
their outcomes within the species/entity declaration itself (calling a
function when the outcome is complex) instead of the current split where
species carry payload fields and items carry the consume composition; and
the status/outcome boundary needs a cleaner implementation. Not this
turn. **Verification:** append under a dated heading; read-through.

**Steps:** append to `docs/needs-rewrite/BACKLOG.md`:

~~~~ text
## 2026-08-31 — Species compose outcomes (rename follow-up)

Frog species should operate like items: compose their own outcomes
within the species (item) declaration itself — or call a helper function
when the outcome is complex — rather than today's split (species carry
`catch_outcome`/`spawn_outcome` payload fields; items carry
`_SPECIES_OUTCOMES`). The status/outcome boundary needs a cleaner
implementation: a **status** is persistent scope-aware state in the
status store; an **outcome** is the consequence of an action and may
invoke statuses (never the reverse). Tracked from the 2026-08-31 rename
plan (D5).
~~~~

### T9 — Integration: verify, migrate dev DB, commit

**Files:** dev DB `data/cazzubot-dev.db` (mutation via migration 007),
commits.

**Why:** the renamed DDL cannot boot until the dev DB table is renamed.
**Verification:** full suite + boot check.

**Steps:**

1.  `uv run ruff check . && uv run ruff format --check . && uv run basedpyright && uv run pytest`
    — all green.
2.  Apply migration 007 to the dev DB (dry-run first, then commit):
     -  `uv run python scripts/migrate.py --db data/cazzubot-dev.db --only 007_status_contribution`
        (expect the plan line)
     -  `uv run python scripts/migrate.py --db data/cazzubot-dev.db --only 007_status_contribution --commit`
        (backup written to data/)
3.  Boot check (dev): `uv run python main.py -d` — starts cleanly against
    the migrated DB (verify\_schema accepts `status_contribution`); exit.
4.  Prod: **no mutation** — prod DB stays as-is (006 still pending there;
    bot stopped). Deploy-time step, user-authorized per operation.
5.  Commits (one per task, unsigned per host gotcha):
    `git -c commit.gpgsign=false commit -m "…"` after each coherent task
    is green. Suggested messages: T1 “refactor(statuses): rename effects
    store to statuses (core + wiring)”; T2 “refactor: statuses/outcomes
    wording in experience + inventory prose”; T3 “refactor(outcomes):
    frog species outcome library + item outcomes”; T4 “test(outcomes):
    update tests for the effects -> statuses/outcomes rename”; T5
    “feat(migrations): 007 rename effect\_contribution -> status\_
    contribution”; T6 “docs(statuses): rename EFFECTS.md -> STATUSES.md,
    update live docs”; T7 “docs: add CONTEXT.md canonical terms”; T8
    “docs(backlog): species compose outcomes follow-up”.


Decisions (user-reviewable)
---------------------------

 -  **D1 — species-side behaviors are OUTCOMES, not statuses** (approved
    2026-08-31 with change): the frog registry is an **outcome library**
    (`plugins/frogs/outcomes.py`) — `OutcomeKey`, the `Outcome` protocol,
    `OutcomePayload`, handlers `ExpOutcome`/`ReactionOutcome`/
    `RoleOutcome`/`ClusterOutcome`; species fields `catch_outcome`/
    `spawn_outcome`. Outcomes may *invoke statuses* through `bot.statuses`
    (reaction/role publish contributions); the reverse never happens.
    Cluster's burst is an outcome, not an on-spawn status — the review
    called it an on-catch outcome; the implemented trigger stays
    spawn-side today, so the field is `spawn_outcome` (moving the trigger
    is a behavior change, out of scope — flag if wanted).
 -  **D2 — `FrogEffect` → `FrogStatus` kept** (identity/source enum),
    with the recorded future intention of moving the frog identity
    concept to outcomes when species-level outcome composition lands
    (D5). Near-names `FrogState`/`FrogStatus` coexisting is accepted.
 -  **D3 — migration 006 stays frozen history**: it still creates
    `effect_contribution`; 007 renames it. On prod, 006 then 007 run in
    order at deploy.
 -  **D4 — lifecycle “revertible/deferred effects” stays**: a different
    paper-derived concept (undo stacks), not the status store; renaming it
    is a separate follow-up if wanted.
 -  **D5 — species-compose-outcomes is a BACKLOG item** (T8), not this
    turn: species should compose outcomes within their declaration like
    items do (calling a helper for complex outcomes), and the
    status/outcome boundary needs a cleaner implementation.


Risks & Retirement
------------------

 -  **Risk: boot guard vs un-migrated DB** — mitigated by T5/T8 ordering
    (migrate dev before booting renamed code).
 -  **Risk: missed “effect” occurrence** — verified by grep sweep in T6/T8
    (`grep -rIn 'effect' --include='*.py' .` expected residual: generic
    English only).
 -  **Rollback**: revert commits; dev DB backup
    `data/007_status_contribution_backup-*.db`; re-running the old code
    needs the table renamed back (documented in the T5 module docstring).
 -  **Retirement**: migration 007's `needs` gate becomes False forever
    after apply; the module stays as a record like 006.


Execution Readiness View
------------------------

~~~~ text
Execution Readiness View:
- Intent Lock: rename effects -> statuses (the store: cazzubot/statuses.
  py, bot.statuses, status_contribution); species-side and item behaviors
  -> outcomes (plugins/frogs/outcomes.py, OutcomeKey, catch_outcome/
  spawn_outcome, _SPECIES_OUTCOMES) — outcomes may invoke statuses, never
  the reverse; no behavior changes
- Scope Fence: seams, lifecycle effects, generic-English "effect",
  historical docs and migration 006 untouched; prod DB untouched;
  species-declares-outcomes refactor deferred to backlog (D5/T8)
- Baseline Lock: baseline docs are historical records, not edited
- Approved Behavior: existing suite must stay green (684 tests + new
  migration test)
- Owner / Contract Constraints: bot.statuses owns the status store; items
  and species compose outcomes; outcomes invoke statuses; species ->
  outcomes import edge one-way
- Compatibility Boundary: stored strings unchanged; table + converge tag
  renamed via migration 007; boot guard requires dev DB migrated
- Retirement Boundary: migration 007 stays as a record after apply;
  historical docs keep old terminology
- Task Batches: T1 core, T2 consumers, T3 frog outcomes slice, T4 tests,
  T5 migration 007, T6 docs, T7 CONTEXT.md, T8 backlog entry, T9 verify +
  dev migrate + commits
- Test Obligations: full pytest / ruff / basedpyright after each batch;
  T5 focused migration test
- Review Gates: user approved the plan 2026-08-31 with D1 changed (see
  Decisions); one commit per task
- Drift / Rewind Rules: on suite failure in a batch, fix that batch
  before continuing; migration 007 dry-run before --commit on dev
- Evidence Required Before Completion: full suite green; dev DB migrated
  and boots; grep sweep shows no concept-name "effect" in live
  code/docs
- Advisory Boundary: method-pack execution guidance only; not
  GateDecision, PolicySnapshot, or completion authority
~~~~


Execution Route
---------------

~~~~ text
Execution Route:
- Decision: inline
- Evidence: a cross-cutting mechanical rename — every task edits shared
  symbols (OutcomeKey, bot.statuses, _SPECIES_OUTCOMES); parallel
  subagents would fight over the same lines; the slices are sequential
  and each is small
- Fallback: none needed
- User confirmation required: yes — the user asked to "plan first";
  execution starts only on approval (given 2026-08-31 with the D1
  change to outcomes; approved)
~~~~

