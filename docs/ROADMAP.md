# Frog Species & Effects — Expansion Roadmap

> Status: **Phases 0–3 implemented** — asset core (typed, enum-declared
> assets), species catalog + effects (payload-driven, enum-keyed registry,
> `SpeciesKey` typed keys), the generic game stores (`bot.inventory`
> holdings + `bot.member_effects` modifiers), the core event bus
> (`bot.events` + frog domain events), and the DB migration
> (`scripts/migrate_frog_species.py`, run while stopped before booting
> the live dev/prod DBs) are in, suite green. Phase 4 (docs) is partially
> done (ASSETS/ROADMAP/BACKLOG updated; PLUGINS/MANUAL_TEST pending).
> Complements `docs/ASSETS.md` (the asset-management design this roadmap
> builds on); supersedes nothing.

## Why

The frog economy is currently a single-token model: catch a frog, consume it
for a fixed amount of seasonal exp. There is no variety — one species
("normal"), one frozen state, hardcoded values (`_EXP_PER_FROG` in
`plugins/frogs/logic.py`: 10 normal / 3 frozen), and a column-per-type
schema (`member_frog.normal/frozen`, `FrogTypeEnum`) that makes adding a new
frog type a schema change every time.

This roadmap expands frogs into a content-driven system: **multiple species**
with distinct art, rarity, catch effects and consume effects, a real
**per-member inventory**, and the **core asset-management infrastructure**
needed to organize species art.

## Backlog tie-ins

- **Core asset management** (`docs/BACKLOG.md`, full design in
  `docs/ASSETS.md`) — its stated prerequisite is exactly this frog catalog
  rework: inventory replacing `member_frog.normal/frozen` + `FrogTypeEnum`,
  effects via a typed payload-driven registry. This roadmap implements that
  prerequisite and the static half of the asset system.
- **Core event bus — `bot.events`** — **implemented (2026-08-14)** as a
  typed observation seam in `cazzubot/events.py`: plugins emit domain
  events after their transactional work (`FrogCapturedEvent` /
  `FrogConsumedEvent` from `plugins/frogs/events.py`); subscribers are
  awaited in order and their failures are isolated, so observers can never
  break the emitter. Frog effects deliberately do **not** ride the bus —
  they are entity-bound and transactional (the species' own behavior),
  while observations (badges, milestones) are the bus's job.
- **Badge / achievement system (future)** — the first real bus consumer.
  Badge definitions in code (like species), a `member_badge` state table,
  and a **trigger registry reusing the effects convention**: `TriggerKey`
  enum → typed trigger configs (e.g. `message_contains`, `frog_captured`
  with species/rarity filters) → handlers that subscribe to the bus
  (domain events) or gateway events (message content). A rare-frog catch
  badge is then: frog effect fires inline during the capture, `frog_captured`
  is emitted after, and the badge trigger observes it — both fire, neither
  knows the other.
- **Shop / dishes (recipes)** — deferred. The catalog schema is shaped so a
  `frog_recipe` table (inputs JSON → output species) and shop views can ride
  on top without schema churn.
- **Fold `daily`/`quarterly` into owning plugins** — untouched; the
  quarterly freeze wrapper stays, only its body changes.

## Goals

1. A catalog of catchable frog species — each with a key, name, rarity,
   description, art, spawn weight, catch effect, and consume effect.
2. A real inventory: per member, per species, per state (normal/frozen).
3. Effects live in code (a registry); *which species exist, their art,
   rarity, weights* live in catalog rows — swappable without deploys.
4. One way to get an asset (declaration), one way to reference it (keyed
   lookup), one way to verify it (boot drift check) — per `docs/ASSETS.md`.
5. Migration path for the existing normal/frozen frogs (dev + prod DBs).
6. Nothing downstream changes: delivery stays URL-based, so templates and
   embeds keep working untouched.

## Non-goals (this iteration)

- Dishes/recipes and the combine UI.
- A shop / currency beyond frogs + exp.
- Admin upload of assets (the dynamic path in ASSETS.md) — static-only.
- The core event bus.
- Per-user or per-guild asset variants (single-guild bot by design).

## Phases

### Phase 0 — Decisions
Settle the open decisions (below): species set + effects, art assets, asset
channel ids, whether frozen stays an inventory state.

### Phase 1 — Asset core (new `cazzubot/assets.py`) ✅ implemented 2026-08-14

- `asset` registry table (schema run at boot like settings/scheduler).
- **Typed declarations** — a plugin declares its assets as an enum
  (`Plugin.asset_decl`); each member's value is an `AssetSpec(kind, path)`
  and the member IS the reference. The registry key is **derived** from
  the enum identity (`asset_key(member)`), never hand-written, so a
  reference to an undeclared asset cannot be spelled — the old
  referenced-key boot check and its static test are structurally
  redundant and gone. (`AssetKind` is declaration metadata for internal
  documentation — nothing consumes the `kind` column yet; a future
  kind-driven feature may also nest its members for a better workflow.)
- `Assets` service on `CazzuBot`:
  - `reconcile()` — hash each declared asset's file (walking the enum),
    upsert rows (changed hash → re-sync), fail-fast on a missing file
    (mirrors `Database.verify_schema`).
  - `sync_cdn()` — upload new/changed blobs to the private asset channel,
    store the returned attachment CDN URL in the row; skipped with a boot
    warning when no channel is configured.
  - `get(asset: Enum)` — the URL, for templates/embeds.
- Boot wiring: `reconcile()` at the end of `_on_starting`; `sync_cdn()` as a
  `StartedEvent` listener (REST is up then — same ready-gate reasoning as
  the scheduler).
- `Config.asset_channel_id` from `ASSET_CHANNEL_PROD`/`ASSET_CHANNEL_DEV`
  (common-noun-first naming, side-selected like `GUILD_ID_*`); `.env.example`
  documents both.
- Art files under `plugins/frogs/assets/` (committed — not gitignored).

**Acceptance:** with a declared asset present and a channel configured,
`bot.assets.get(FrogAsset.LEAF_FROG)` returns a URL; a missing file aborts
boot.

### Phase 2 — Species catalog + inventory + effects (`plugins/frogs/`) ✅ implemented 2026-08-14

- Schema: frog holdings move to the generic `inventory` store (see Data
  model — `frog:species:state` items); `member_frog(uid, capture)`
  (normal/frozen columns dropped); `member_frog_log.type` now stores the
  species key. **No `frog_species` table** — species are defined entirely
  in code (see below).
- `FrogTypeEnum` → `FrogState` (normal|frozen) in `cazzubot/models.py`;
  update all usages (cog, db, factory, logic, quarterly, tests).
- New modules:
  - `species.py` — `Species` dataclass + `SPECIES` registry, **defined
    entirely in code** (no catalog rows: a DB table would create a proxy
    interface for tuning and balancing, which the owner wants to avoid —
    tuning = editing `species.py`); keys are typed (`SpeciesKey` in
    `cazzubot/models.py`, strings only at the data boundary), `by_key`
    / `roll_species(rng)` (weighted pick, seedable for tests), and a
    species' `art` is a `FrogAsset` member (`plugins/frogs/assets.py`) —
    the declaration IS the reference, so art cannot be misspelled.
  - `effects.py` — `EffectKey` enum (each member's value IS its handler)
    + per-effect `*Payload` dataclasses + `Effect` protocol; service
    layer (no hikari — `bot` is only a parameter), so the CSR boundary
    test stays green.
- Capture flow: roll the species at spawn time (the visible frog **is** the
  species — message shows its art/name); carry the species in the button
  custom_id (`frog:catch:{cid}:{species_key}`, boot sweep matches the
  prefix); on click: inventory +1 (state normal), capture log with the
  species key, run the catch effect, present the template with new
  `{species}`/`{species_art}` placeholders.
- Commands: `/frog consume [species] [amount] [state]`; `/frog profile`
  renders the species inventory; new public `/frog catalog` (rarity,
  description, art); `/frog spawn`/`fake` accept an optional `[species]`
  for owner testing; the old `frog_type` option is removed.
- Quarterly freeze folds `frog_inventory` states (normal→frozen per
  species). The `exp_multiplier` buff stays deferred (v1 effects = `exp`
  only, per the Phase 0 decision).

**Acceptance:** capture grants the visible species; consume exp differs per
species and frozen state; effects fire; profile shows the inventory; all
tests green.

### Phase 3 — Migration (`scripts/migrate_frog_species.py`) ✅ implemented 2026-08-14

- Mirrors `scripts/migrate_poll_cid.py`: `--db`, `--backup-dir`, dry-run by
  default, `--commit` to apply, idempotent (skips when the legacy shape is
  absent — the generic `inventory` table present or no `normal`/`frozen`
  columns).
- Steps: backup → create the generic `inventory` table (no species rows —
  species are code-defined) → move `member_frog.normal`/`.frozen` into
  inventory rows under the default species (`leaf_frog`, item strings
  derived from `FrogItem.key`, skip zero qty) → rebuild
  `member_frog_log` with the new DDL (its `type` default changed from
  `'normal'` to the species key, so a plain row rewrite would fail the
  schema guard), rewriting `'normal'|'frozen'` types to the species key
  during the copy → drop the columns.
- Run while the bot is stopped, before booting the new code (the boot schema
  guard refuses the legacy shape).
- Legacy PG-migration tooling (`scripts/verify_migration.py`,
  `boot_check_migrated.py`, `sqlite_to_pg.py`) references the old columns —
  marked deprecated in docstrings rather than updated (PG migration is done;
  this migration supersedes them).

**Acceptance:** a migrated dev DB boots the new code with correct inventory;
dry-run reports exact counts. Covered by `tests/core/test_migrate_frog_species.py`
(legacy-shape build → plan/migrate → new shape asserted, idempotence, and a
full boot through the real schema guard).

### Phase 4 — Tests + docs

- Unit/cog/driver coverage (see Testing below).
- `docs/ASSETS.md` status flip to "implemented (static path)";
  `docs/BACKLOG.md` update; `docs/PLUGINS.md` (`bot.assets`/`bot.events`/
  `bot.inventory`/`bot.member_effects` under "Services available on the
  bot"); `docs/MANUAL_TEST.md` dev-guild items.

## Data model

Species are **not** rows — the catalog is the code registry in
`plugins/frogs/species.py` (no `frog_species` table; tuning = editing code,
deliberately no DB proxy for it). Member state follows the decomposition
principle (backlogged with the game features): **scalar per-feature state**
in narrow per-feature tables, **repeating shapes in generic core stores**
(`inventory` for holdings, `member_effect` for modifiers), **history in
append-only logs**, and the "whole member" is a derived profile view
composed on read — never a stored row.

```sql
CREATE TABLE IF NOT EXISTS inventory (      -- generic holdings (core)
    uid  INTEGER NOT NULL,
    item TEXT NOT NULL,                      -- derived from a typed key
    qty  INTEGER NOT NULL DEFAULT 0,         -- e.g. frog:leaf_frog:normal
    PRIMARY KEY (uid, item)
);

CREATE TABLE IF NOT EXISTS member_effect (  -- generic modifiers (core)
    uid        INTEGER NOT NULL,
    key        TEXT NOT NULL,                -- MemberEffectKey.EXP_MULTIPLIER
    value      REAL NOT NULL,
    expires_at TEXT,                         -- NULL = permanent (lazy expiry)
    PRIMARY KEY (uid, key)
);

CREATE TABLE IF NOT EXISTS member_frog (   -- lifetime capture counter only
    uid     INTEGER PRIMARY KEY,
    capture INTEGER NOT NULL DEFAULT 0
);
```

(`member_frog_log` keeps its shape; `type` stores the species key.)

## Effects registry (implemented — typed, payload-driven)

```python
# plugins/frogs/effects.py — service layer, no hikari imports (bot is a
# TYPE_CHECKING-annotated parameter, so effects can do anything at runtime)
class EffectPayload(Protocol):
    """A species-side effect configuration (key selects the effect)."""

    key: EffectKey


class Effect(Protocol):
    async def catch(
        self, bot, payload: EffectPayload, *,
        uid: int, species_key: str, now: pendulum.DateTime
    ) -> None: ...

    async def consume(
        self, bot, payload: EffectPayload, *,
        uid: int, species_key: str, amount: int,
        state: FrogState, now: pendulum.DateTime
    ) -> None: ...


class ExpEffect:
    """consume: seasonal exp per payload values."""
    ...


class EffectKey(Enum):
    """The registry itself — each member's value IS its handler."""

    EXP = ExpEffect()


@dataclass(frozen=True, slots=True)
class ExpPayload:
    """The ``exp`` effect's configuration — per-species values."""

    key = EffectKey.EXP
    exp: int
    frozen_exp: int
```

- Each effect owns a **payload dataclass**; a species definition carries
  payload *instances* (`catch_effect`/`consume_effect`), so one effect
  class is reusable with different values (the `exp` effect powers both
  the 10/3 Leaf Frog and the 20/6 Classy Frog) and a species never
  carries fields for effects it doesn't use. The species' `exp`/
  `frozen_exp` fields are gone — they live in `ExpPayload` now.
- The **`EffectKey` enum IS the registry**: each member's value is its
  handler object, so dispatch is `payload.key.value.catch(...)` — a plain
  attribute access, no lookup table, no `register_effect`. A key without
  a handler cannot exist, so the developer-error guard is structural:
  species effect fields are payload-typed (a typo'd effect name cannot
  compile) and an enum member always has a handler.
- Effects are **decoupled from the controllers**: hooks receive the bot +
  the species' payload, so an effect can do anything — grant exp, spawn a
  cluster of frogs across channels via the scheduler, hand out roles —
  without the cog or factory knowing about it.
- v1 ships `exp` only. `exp_bonus` (catch; instant seasonal exp via
  `exp_db.add_exp_log(source=FROG)`) and `exp_multiplier` (catch; timed
  ×message-exp buff via `member_buff`, applied in
  `experience.logic.award_exp`) stay unimplemented until a species needs
  them.
- Adding a new effect = one handler class + one enum member
  (`CLUSTER = ClusterEffect()`) + one payload dataclass; then point a
  species' side at a payload instance.

## Testing

- Unit: weighted roll (seeded rng), species seeding idempotence, inventory
  upsert/decrement, consume math per species+state, freeze flip, buff
  expiry/apply, effect registry, asset reconcile drift (missing/changed file
  → abort/requeue).
- Cog: `/frog consume` per species/state (incl. the confirm-menu flow),
  profile inventory rendering, `/frog catalog`.
- Driver (`tests/driver.py` + `tests/integration/`): capture button press →
  species granted + log + catch message; consume end-to-end; `full_bot`
  tests seed the asset registry or stub `bot.assets.get` so nothing touches
  the network.
- Boundary: new service modules (`species.py`, `effects.py`, `db.py`,
  `logic.py`) stay hikari-free (the existing CSR sweep covers them).
- Migration: unit test against a temp DB built in the old shape (build old
  schema, seed rows, run the migration logic, assert inventory/log rows).

## Phase 0 — Decisions (resolved 2026-08-14)

| Decision | Resolution |
|---|---|
| Iteration scope | As scoped above — shop/recipes, the core event bus, and admin upload all deferred |
| Effects list | Typed payload-driven registry (`EffectKey` enum → handler, per-effect payload dataclasses on the species); v1 ships **`exp` only** (`ExpPayload` with per-species values + `frozen_exp`). `exp_bonus`/`exp_multiplier` stay unimplemented until a species needs them |
| Species source | **Fully in code** — the `SPECIES` registry in `plugins/frogs/species.py` is the single source of truth; **no `frog_species` table** (changed from the earlier "code-registered seeds" choice at the owner's request, 2026-08-14: DB rows would create a proxy interface for tuning and balancing — friction to avoid. Tuning = editing `species.py`) |
| Asset depth | **Static-only** — `Plugin.assets` declarations + registry + boot reconcile + CDN sync; no `/asset add` |
| Starter species | **Two** — `leaf_frog` (common, default, exp 10 / frozen 3, art = cirnoFrog emoji) and `classy_frog` (exp 20 / frozen 6 — double normal, art = emoji `1425312054528708639`, downloaded into `plugins/frogs/assets/`) |
| Art assets | **Placeholder files first** — real art dropped in later re-syncs at boot |
| Frozen | **Stays** an inventory state (`normal\|frozen` in `frog_inventory`); quarterly freeze flips states per species |
| Asset channels | Owner creates a private channel per guild; ids → `ASSET_CHANNEL_PROD`/`ASSET_CHANNEL_DEV` in `.env` (pending — boot warns + skips CDN sync until set) |

Still open (non-blocking, code-adjustable later): spawn weights + rarity —
both species default to common / weight 1 (a 50/50 roll) until the owner
tunes them; `classy_frog`'s catch/consume behavior beyond exp is whatever
the `exp` effect gives it.

## Assumptions

- Spawn cadence (`frog_spawn`), the `frog.message` template shape (new
  placeholders only), and the `ConfirmMenu` flow are unchanged.
- The dev DB migrates and live-tests first; the prod DB file migrates with
  the same script while stopped; live testing stays in the development
  guild (guild-safety rule).
- Buff expiry is lazy (read-time), deliberately deviating from "all delayed
  work via the scheduler": the `member_buff` row is authoritative and needs
  no boot re-arm.

## References

- `docs/ASSETS.md` — the asset-management design this roadmap builds on
- `docs/BACKLOG.md` — parked items (asset management, event bus, shop)
- `plugins/frogs/` — the current implementation being reworked
- `docs/PLUGINS.md`, `docs/TESTING.md`, `docs/MIGRATION.md`
