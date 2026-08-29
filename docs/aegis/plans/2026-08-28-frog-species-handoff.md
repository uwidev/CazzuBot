Frog Species — Phase 2 Execution Handoff (Species Implementation)
=================================================================

> Purpose: a **fresh chat context** reads this file, then immediately does
> **Phase 2**: implement the five FROG.md frogs on top of the Phase-1
> separation. Phase 1 (the items / frog / effects **separation**, Option B)
> is **DONE** and committed (see Current state). This file is the boot sheet;
> the plan (`docs/aegis/plans/2026-08-28-frog-species.md`) is the code
> reference for the code shapes. **Do NOT re-do the Phase-1 slice** (plan
> Task 2 + Task 3's composition part + Task 9's Phase-1 bullets): those ship
> tested. Execute the plan's remaining tasks (Phase 2 task map) and fire what
> Phase 1 deliberately left unfired.
>
> Written: 2026-08-28 (Phase 1) · Updated 2026-08-29 (Phase 1 closed — this
> is now the Phase 2 boot sheet).


Mission (Phase 2)
-----------------

Implement the five species exactly as specified in `docs/FROG.md`, reusing
the Phase-1 separation (typed seams, generic scope-aware modifiers,
`RoleConverger`, item-owned consume composition — all shipped and tested):

1.  **Species keys, registry, art** (plan Task 1): `FrogItemKey` +=
    POG/FROGGERS/CLASSY/CLUSTER; `Species` gains `spawn_effect` + optional
    `art` (no new fields on the entity beyond that — the item composes
    consume); `SPECIES` = five entries with the FROG.md weights
    (1000/200/50/200/300); the `frog_item_key` helper splits out of
    `db.FrogItem` so `effects.py` and `db.py` share one derivation; declare
    the FROG\_POG/FROG\_FROGGERS/FROG\_CLASSY assets (the placeholder PNGs
    **already exist** in `plugins/frogs/assets/` — skip the plan's
    PNG-creation snippet).
2.  **The new frog items** (plan Task 3, composition parts): `_SPECIES_EXP`
    rows (D1/D2 defaults), `_SPECIES_CONSUME` entries composed from the
    already-shipped `ReactionPayload`/`RolePayload`, `classy_role_ids()`,
    six bare `Item` literals + glue (frozen reuses normal art per D8), and
    the `_consume_blurb` isinstance branches (see the Phase-1 `items.py`).
3.  **Reaction listener** (plan Task 4): `plugins/frogs/reactions.py`
    (guild-scoped via `guild_listener`) + `extensions` += it. The seam and
    the identity merge ship; this is the consumer that rolls the chance.
4.  **Cluster** (plan Task 5): spawn-side hook (`ClusterEffect` +
    `ClusterPayload` + `EffectKey.CLUSTER`), `Species.spawn_effect` wiring,
    factory short-circuit + uncatchable guard, `spawn_impl` injection at
    load, `FakeRest.fetch_guild_channels`.
5.  **Season reset** (plan Task 6): quarterly “use it or lose it” — every
    frog becomes a Basic Frog (`season_reset_frogs` replaces `freeze_frogs`);
    the tag/cadence/arming stay.
6.  **Catalog display** (plan Task 7): `/frog catalog` describes all five;
    Cluster shows a burst note, never an exp line (it has no oracle entry).
7.  **Plugin wiring + driver e2e** (plan Task 8): converger registration,
    `EffectsClearedEvent` subscription, `ClusterEffect.spawn_impl`
    injection — the things Phase 1 shipped **tested but unwired** — plus
    end-to-end offline driver tests.
8.  **Docs close-out** (plan Task 9): PLUGINS/SYSTEMS/ROADMAP/EFFECTS/INDEX
    updates + baseline mark.

Explicitly deferred: nothing — the species themselves are the point. Do not
extend the Phase-1 “tested-but-unwired” stance beyond what Task 8 wires.


Read order
----------

1.  **THIS file** — Phase-2 scope, tasks, conventions, landmines.
2.  **`docs/FROG.md`** — the spec (the five frogs + the reapplication rule).
3.  **`docs/needs-rewrite/EFFECTS.md`** — the seam/contribution design +
    the Phase-1 record (D11/D3, `ExpEffect` retirement). **`ExpEffect`/`EXP`
    stays unused — do not resurrect it; exp is item-owned.**
4.  **`docs/aegis/plans/2026-08-28-frog-species.md`** — the full 9-task
    plan; **use it as the code reference**. Execute **tasks 1, 3–9** —
    task 2 (seams + reaction/role effects + converger) is already shipped
    (Phase 1). Its header's old “Phase 1 open” marker is historical.
5.  **`docs/aegis/baseline/2026-08-28-frog-species-baseline.md`** — the
    Phase-0 measured state (the Phase-1 work built on it).
6.  **`docs/needs-rewrite/PLUGINS.md`** — required feature context
    (AGENTS.md; the top-level `docs/PLUGINS.md` path moves to
    `needs-rewrite/` in this tree's docs reorg).


Decided model (do not re-derive)
--------------------------------

 -  **D11 — the ITEM composes, effects modify.** What consuming an item
    does is the item's decision: exp (its `frog_exp` oracle) plus composed
    effect applications (`_SPECIES_CONSUME` beside the oracle). Species
    carry no consume declaration. Effects are generic, scope-aware
    modifiers callable from any entry point.
 -  **D3 — identity is the effect, not the item.** Contribution key
    `(scope, seam, source)` with **source = effect identity**
    (`FrogEffect.REACTION` / `CLASSY_ROLE`), never the item id; the item is
    `payload["from"]` provenance. Reaction semantics: strongest chance wins
    while active, weaker consumes never downgrade, every consume extends
    the window additively, expiry = fresh start; the merge is feature-side
    in `ReactionEffect.consume` (implemented + tested in Phase 1).
 -  **Constants:** Classy exp **200** (D1), frozen = **half** (D2),
    season reset = every frog → **Basic** (D10), reaction chance
    Pog **1%** / Froggers **7%**, role duration **3h** (dev
    1542294599358353430 / prod 1542293782588952696), cooldown **10s** (D4),
    reaction emoji = `FrogAsset.FROG_FROGGERS` (D5), cluster radius **±2**,
    4–10 children, **0.75s** stagger (D6), cluster has **no art/item**
    (D7/D8), rarity strings (D9).
 -  **Fossil:** `ExpEffect`/`EXP` stays but unused — slated for removal;
    recorded in EFFECTS.md. Leave it alone.

### Phase-1 drift fixes — KEEP these when copying plan blocks

The shipped Phase-1 code already applies several corrections to the plan's
reference snippets. Preserve them in the Phase-2 tasks (they are tested):

 -  `RoleConverger` reads `member.role_ids` (`current = set(member.role_ids)`)
    — hikari Members have **no** `.roles` attribute.
 -  Contributions are `EffectContribution` **dataclasses**: access
    `contrib.payload.get("role_id")` with an `isinstance(role_id, int)`
    guard — never `c["role_id"]` / `c.get(...)`.
 -  Reaction window math: a stronger consume REPLACEs with
    `remaining + new duration` computed at the **current** `now` — a 1h Pog
    at T then a 1h Froggers at T+5m expires at **T+2h** (not T+2h05m); a
    weaker EXTEND then moves it to **T+3h**. Tests assert this.
 -  `Config` is a **frozen dataclass**: never assign
    `bot.config.guild_kind` in tests (the fixtures already boot with
    `guild_kind="development"`). To exercise the production role id, call
    `RolePayload.role_id_for("production")` directly.
 -  Spying a handler: patch the **singleton instance attribute**
    (`monkeypatch.setattr(EffectKey.X.value, "consume", spy)`) — a class
    patch binds the instance and breaks the call signature.
 -  `ReactionEffect` compares chances via the engine's isinstance-guard
    pattern (stored payload values are JSON-reloaded objects).
 -  `tests/fakes.py`: `add_role_to_member`/`remove_role_from_member` now
    **mutate `member.role_ids`** (role tests assert real state).
    `fetch_guild_channels` is still missing — that is Task 5's fakes change.


Current state (Phase 1 closed, 2026-08-29)
------------------------------------------

 -  **Committed on `main`** (HEAD `3c20c0d`, ahead of origin/main 9; every
    commit unsigned via `git -c commit.gpgsign=false`):
    `090df43` (P1.1 item-owned consume composition + dispatcher test),
    `aaae3f0` (P1.2 typed seams), `7d768e9` (P1.3 generic modifiers +
    RoleConverger), `43a366d` (P1.4 reaction/role tests + fakes role
    mutation), `fbc9431` (P1.5 docs + ownership records),
    `3c20c0d` (ruff-format follow-up).
 -  **Suite: 693 green** (Phase-0 baseline 684; +9). `ruff check .` clean;
    `ruff format --check` clean. `basedpyright`: **27 errors, ALL
    pre-existing in untouched files** — `cazzubot/manifest/lines.py` (10),
    `tests/plugins/frogs/test_extension.py` (8),
    `tests/plugins/fun/test_extension.py` (2), `cazzubot/plugin.py` (2),
    `tests/plugins/experience/test_extension.py` (1),
    `tests/core/test_items.py` (1), `scripts/*` (3). Keep them at 27 —
    **no new errors**.
 -  **Working tree still dirty** with the user's UNCOMMITTED WIP: the
    effects redesign core files, the docs reorg (deleted/moved docs,
    untracked `docs/FROG.md`/`docs/SYSTEMS.md`/`docs/aegis/`), the frog
    placeholder PNGs, and the migration scripts. **Do not commit, stash,
    squash, or edit anything outside your task's file list.**
 -  **Wired now:** item consume composition (oracle → composed-modifier
    dispatch → `FrogConsumedEvent`); typed `FrogSeam`/`FrogEffect`;
    `ReactionEffect` (identity-by-effect merge — one row across items,
    strongest wins, additive window, no downgrade, fresh after expiry);
    `RoleEffect` + `RoleConverger` (publish → converge → role added;
    expiry/clear → removed; idempotent; known-ids-only) — proven through
    `full_bot` + `FakeRest`.
 -  **Unfired (Phase 2 fires these):** the reaction **listener** module, the
    Cluster **spawn hook** + factory short-circuit + `spawn_impl` injection,
    the quarterly **season reset**, the **catalog** guards, the species
    **items** (`_SPECIES_EXP`/`_SPECIES_CONSUME`/`FrogItems` members), and
    the plugin **wiring** (converger registration + `EffectsClearedEvent`
    subscription — `RoleEffect.publish` fail-fasts with `KeyError` until
    the converger is registered, by design).
 -  **Existing tests that Phase 2 updates (not bugs):**
     -  `tests/plugins/frogs/test_species.py` — `test_catalog_is_single_species`
        (asserts `[BASIC]`), `test_species_art_is_a_declared_asset_member`
        (art always a `FrogAsset`), and roll expectations (weight 1.0 →
        FROG.md weights). Any test constructing `Species(...)` (e.g.
        `test_capture_dispatches_species_payload` in `test_effects.py`) must
        pass the new `spawn_effect` field.
     -  `tests/plugins/frogs/test_items.py` —
        `test_species_consume_composition_is_basic_only` (asserts
        `_SPECIES_CONSUME == {BASIC: ()}`) and the blurb-oracle tests grow.
     -  `tests/plugins/frogs/test_extension.py` — catalog expects Basic
        “Leaf Frog”, one species field (plan Task 7 updates).
     -  `tests/plugins/frogs/test_cadences.py` — the quarterly tests get the
        species-conversion leg (freeze → season reset); the three
        basic-only freeze tests keep passing unchanged.


Execution route (decided)
-------------------------

 -  **Inline, sequential T1 → T3 → T4 → T5 → T6 → T7 → T8 → T9.**
    Files are shared (species.py/effects.py/items.py/factory.py across
    tasks); do not fan out. Order matters; the plan's TDD cycle per task
    stands.
 -  **TDD Route: strict** (recorded auto decision in the plan): behavioral
    slices write the failing test first → RED → minimal change → GREEN.
    Mechanical slices (registry rows, item literals) go direct + regression.
 -  **One commit per task**, unsigned
    (`git -c commit.gpgsign=false commit -m "..."` — see Landmines), only
    after that task's verification. Stage **only** task-owned paths — the
    WIP tree is not yours to commit.


Phase 2 task map
----------------

| #   | Deliverable                                                                                                                                                                                                                                                                                                                                                                                                                                       | Code source (plan reference)                                                             | Verify                                                                                                                                                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | Species keys + registry + art: `FrogItemKey` += 4; `Species` += `spawn_effect`, `art` optional; five `SPECIES` entries (FROG.md weights); `frog_item_key` helper split into `effects.py` (`db.FrogItem.key` delegates); `FrogAsset` += POG/FROGGERS/CLASSY (PNGs exist — skip the plan's creation snippet); factory art-None guards; update the two single-species tests + any `Species(...)` constructor call sites (pass `spawn_effect`)        | plan Task 1 (all steps; keep the drift fixes; drop the PNG loop)                         | `uv run pytest tests/plugins/frogs/test_species.py -q`; `uv run ruff check plugins/frogs cazzubot/models.py tests/plugins/frogs/test_species.py`; `uv run basedpyright`                                                                                                    |
| T3  | Item-owned consume (composition parts): `_SPECIES_EXP` rows (Pog 30/15, Froggers 300/150, Classy 200/100, 4 keys — no cluster); `_SPECIES_CONSUME` entries (ReactionPayload 0.01/1h, 0.07/1h; RolePayload dev/prod/3h); `classy_role_ids()`; six `FrogItems` members + glue (frozen reuses normal art); `_consume_blurb` isinstance branches; update `test_species_consume_composition_is_basic_only` + blurb tests                               | plan Task 3 steps 2–6 (`_consume_item`/pipeline already shipped in Phase 1 — keep as-is) | `uv run pytest tests/plugins/frogs/test_items.py tests/plugins/frogs/test_effects.py -q`; `uv run ruff check plugins/frogs tests/plugins/frogs`; `uv run basedpyright`; `uv run pytest tests/plugins/frogs -q`                                                             |
| T4  | Reaction listener: new `plugins/frogs/reactions.py` (`guild_listener`-scoped MessageCreateEvent; 10s in-memory cooldown; strongest single row; no-op while emoji unpublished) + `extensions += "plugins.frogs.reactions"`; tests `tests/plugins/frogs/test_reactions.py` (fakes `add_reaction` + `FakeMessageCreateEvent` already exist)                                                                                                          | plan Task 4 verbatim                                                                     | `uv run pytest tests/plugins/frogs/test_reactions.py -q`; `uv run ruff check plugins/frogs tests/plugins/frogs/test_reactions.py`; `uv run basedpyright`; `uv run pytest tests/core/test_csr_boundary.py tests/integration/test_guard_driver.py -q`                        |
| T5  | Cluster: `ClusterEffect`/`ClusterPayload`/`EffectKey.CLUSTER` (spawn hook, hikari-free numeric GUILD\_TEXT check, tracked background children, 0.75s stagger); `Species` cluster entry wires `spawn_effect`; factory spawn short-circuit + uncatchable guard; `ClusterEffect.spawn_impl` injection (load/unload); `FakeRest.fetch_guild_channels`; tests `tests/plugins/frogs/test_cluster.py` + the T1 species-registry `spawn_effect` assertion | plan Task 5 verbatim (drop nothing; keep effects.py hikari-free)                         | `uv run pytest tests/plugins/frogs/test_cluster.py tests/plugins/frogs/test_species.py -q`; `uv run ruff check plugins/frogs tests/plugins/frogs tests/fakes.py`; `uv run basedpyright`; `uv run pytest tests/core/test_csr_boundary.py tests/core/test_db_boundary.py -q` |
| T6  | Season reset: `db.freeze_frogs` → `db.season_reset_frogs` (every non-basic stack folds to `frog:basic:normal`, then basic normal → frozen); `on_quarterly_due` calls the new name + comment update; `test_cadences.py` += species-conversion test (the three basic-freeze tests stay green)                                                                                                                                                       | plan Task 6                                                                              | `uv run pytest tests/plugins/frogs/test_cadences.py tests/plugins/frogs -q`; `uv run ruff check plugins/frogs`; `uv run basedpyright`                                                                                                                                      |
| T7  | Catalog: `Catalog.invoke` branch (spawn-effect species → burst note, no consume line; thumbnail art None-check); `test_extension.py` updated (5 fields, “Basic Frog”, classy **\`200\`** exp)                                                                                                                                                                                                                                                     | plan Task 7                                                                              | `uv run pytest tests/plugins/frogs/test_extension.py -q`; `uv run ruff check plugins/frogs`; `uv run basedpyright`                                                                                                                                                         |
| T8  | Plugin wiring + driver e2e: `plugins/frogs/__init__.py` registers `RoleConverger` (seam CLASSY\_ROLE), subscribes `EffectsClearedEvent` (captured bot), injects/clears `ClusterEffect.spawn_impl`; `classy_role_ids()` current; `tests/integration/test_frog_driver.py` adds the consume-Pog / consume-Classy / cluster-driver flows                                                                                                              | plan Task 8 verbatim (both code blocks)                                                  | `uv run pytest tests/integration/test_frog_driver.py tests/plugins/frogs -q`; then the final gate (below)                                                                                                                                                                  |
| T9  | Docs close-out: PLUGINS/SYSTEMS/ROADMAP/EFFECTS (species + wiring records; mark plan implemented)/INDEX; baseline mark                                                                                                                                                                                                                                                                                                                            | plan Task 9                                                                              | markdown `hongdown -w <changed md files>`; then the final gate                                                                                                                                                                                                             |

**Final gate (after T8/T9):**
`uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run basedpyright`
(still 27 pre-existing errors — no new); markdown finalized with `hongdown -w`.


Environment & conventions (CazzuBot)
------------------------------------

 -  Install/run: `uv sync` (if the uv cache is read-only in your sandbox,
    set `UV_CACHE_DIR=/tmp/uv-cache`); `uv run python main.py -d`; sandbox
    `-s`. No live-bot work is needed — this is code + offline tests.
 -  Verification: `uv run pytest` (targeted paths first), `uv run ruff check .`
    / `ruff format .` (spaces, double quotes, 75 cols), `uv run basedpyright`.
 -  **CSR boundary** (`tests/core/test_csr_boundary.py`):
    `plugins/**/{logic,factory,db,species,effects}.py` must NOT import
    hikari — only `plugins/frogs/factory.py` is exempt.
    `reactions.py` is the hikari home (non-service module);
    `effects.py`/`species.py`/`db.py` stay hikari-free (Cluster's channel
    check uses the numeric GUILD\_TEXT value; its spawn goes through the
    injected `spawn_impl`).
 -  **Guild scoping:** every gateway listener via
    `cazzubot.listeners.guild_listener` (the reactions listener).
 -  **Model boundary:** rows cross module APIs only as dataclasses
    (`fetch_model(s)`); raw `aiosqlite.Row` never leaks.
 -  **Markdown:** personal project — `hongdown -w <files>` after edits
    (never mdformat; it mangles frontmatter).
 -  Item definitions stay bare `Item(...)` literals; exp values stay in the
    `frog_exp` oracle; info card and catalog read the same sources
    (oracle + `_SPECIES_CONSUME`) so display and grant cannot drift.


Landmines (read before executing)
---------------------------------

 -  **`git commit` hangs in this sandbox** (`commit.gpgsign=true`, no gpg
    agent): always `git -c commit.gpgsign=false commit ...`. Never a bare
    `git commit`.
 -  **`push_to_prod.sh` rsyncs `data/` → clobbers the live DB.** Never run
    it; nothing here deploys.
 -  **`scripts/migrate_frog_species.py`** (live-DB species migration, from
    the earlier redesign workstream) is STILL PENDING on live dev/prod
    DBs and NOT in scope — do not run or conflate it with this work. Per
    the plan's Risks: if you live-test this branch on a legacy-shaped DB,
    that migration must run first while the bot is stopped.
 -  **Production guild (293796316193095690) is never mutated.** Phase 2 is
    code + tests only; if you boot the dev bot, dev guild
    (408801760581386245) is free.
 -  **No dead-code creep:** the “tested but unwired” stance was Phase 1's
    explicit decision; Phase 2 fires it (Task 8 wiring) rather than
    extending it. Don't ship extra unused machinery.
 -  **Do not touch the dirty WIP tree** (user's uncommitted effects/docs
    work) — commit only task-owned paths.
 -  **`ExpEffect`/`EXP` stays unused** — exp is item-owned; the docs flag it
    for removal, do not wire it into `_SPECIES_CONSUME`.


Definition of done (Phase 2)
----------------------------

1.  T1, T3–T9 implemented in order; each verified and committed
    (`git -c commit.gpgsign=false`), following the code shapes verbatim
    from the plan's referenced blocks, keeping the drift fixes above.
2.  Final gate green: whole `pytest` suite (≥693 + new), `ruff check .`
    clean, `ruff format --check .` clean, `basedpyright` no new errors
    (27 pre-existing); markdown `hongdown -w`’d.
3.  All five species live per FROG.md: Basic unchanged; Pog/Froggers
    reaction (1%/7%, one shared effect identity); Classy role
    (dev/prod ids) via the registered converger + instant
    `EffectsClearedEvent` revert; Cluster uncatchable spawn explosion;
    the quarterly reset folds every frog to Basic.
4.  Docs carry the species + wiring records and the plan is marked
    implemented (plan Task 9 + `docs/aegis/INDEX.md`).
5.  Report back concisely: files changed, test counts, what is now wired
    vs unfired, and any drift from the reference code + why.


First actions (new context)
---------------------------

1.  `pwd` — confirm the CazzuBot checkout.
2.  `git status --short --branch` — expect the dirty WIP tree (HEAD
    `3c20c0d`, ahead 9); ignore unrelated changes.
3.  `uv sync` (or `UV_CACHE_DIR=/tmp/uv-cache uv sync` if the cache is
    read-only); sanity `uv run pytest tests/plugins/frogs -q`
    (50 green baseline).
4.  Start **T1** (species keys/registry/art + field changes + helper) →
    verify → commit → continue. Pull the code blocks from the plan
    (Task 1 for T1, Task 3 for T3, Tasks 4–8 verbatim), keeping the drift
    fixes and **skipping plan Task 2** (already shipped).
