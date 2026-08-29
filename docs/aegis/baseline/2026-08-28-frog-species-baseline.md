Initial Baseline — Frog Species Infrastructure (2026-08-28)
===========================================================

> Status: Phase-0 measured state of the frog economy infra. The
> frog-species plan executed on top of this; Phase 2 (the five FROG.md
> species) is implemented — see
> `docs/aegis/plans/2026-08-28-frog-species.md` (Status: Implemented).
> The single-species bullet below is historical.

Measured state of the frog economy infra that the frog-species plan
(`docs/aegis/plans/2026-08-28-frog-species.md`) depends on.


Verified facts
--------------

 -  `cazzubot/effects.py` ships the seam/contribution engine: `Scope`
    (member/guild), `ReapplyPolicy.EXTEND/REPLACE/STACK(parked)`,
    `Effects.publish` (external seams converge synchronously at publish and
    schedule tag `effect.converge` at expiry; lazy expiry + prune on read;
    `EffectsClearedEvent` on explicit clear/clear\_scope).
 -  `cazzubot/inventory.py` is the generic holdings ledger; frog stacks are
    `FrogItem(species, state)` wrappers in `plugins/frogs/db.py`.
 -  `plugins/frogs/species.py` is the code catalog: `Species` dataclass
    (key/name/rarity/description/spawn\_weight/catch\_effect/art), `SPECIES`
    tuple, `by_key`, `roll_species(rng)`. Currently ONE species
    (`FrogItemKey.BASIC`, leaf/basic, weight 1.0).
 -  `plugins/frogs/effects.py` is the species-side effect registry:
    `EffectKey` enum (member value IS the handler), `ExpEffect` +
    `ExpPayload`, `Effect` protocol with `catch`/`consume` hooks (bot +
    payload + plain ctx). No hikari imports (CSR sweep
    `tests/core/test_csr_boundary.py` names `logic/factory/db/species/ effects`
    as service files; only carve-out is `plugins.frogs.factory`).
 -  `plugins/frogs/items.py` owns consumption: bare `Item` literals in
    `FrogItems`, consume glue → `_consume_item` (exp from the
    `frog_exp` oracle `_SPECIES_EXP`, then `FrogConsumedEvent`).
    `/inventory consume` (plugins/inventory/extension.py) runs
    `item.consume(bot, uid, amount)` before decrementing.
 -  `cazzubot/assets.py` `Assets.get` returns `<:name:id>` for EMOJI-kind
    assets (usable as a reaction emoji), CDN URL for media.
 -  Event bus `bot.events` (typed, ordered, failure-isolated); no consumers
    subscribed yet.
 -  `cazzubot/listeners.py::guild_listener(loader, event_type)` is THE
    guild-scoped listener registration helper.
 -  `Config.guild_kind` ∈ {production, development} distinguishes guild
    sides at runtime.
 -  Suite was 684 green (effects redesign, 2026-08-27); `ruff` clean;
    `basedpyright` no new errors.
 -  Working tree dirty: effects-redesign work in progress (ahead of
    origin/main 3 commits); no commits from this plan.


Contracts that must hold
------------------------

 -  Service modules (`species.py`, `effects.py`, `db.py`, `logic.py`,
    `factory.py` under `plugins/`) never import hikari — only
    `plugins/frogs/factory.py` is exempt.
 -  Item definitions stay bare `Item(...)` literals; exp values live in the
    `frog_exp` oracle; display and grant must read the same source.
 -  Every guild-scoped listener registers via `guild_listener`.
 -  No new tables: species are code; timed effect rows already live in
    `effect_contribution`.


Out of scope here
-----------------

 -  `scripts/migrate_frog_species.py` (species-model migration) still
    pending on live dev/prod DBs — separate from this plan (no new
    migration needed for added species).
