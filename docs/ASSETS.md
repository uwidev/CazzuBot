# CazzuBot — Asset Management

> **Status:** implemented, static path (boot reconcile + CDN sync). The
> dynamic admin-upload path and scheduler-driven seasonal drops stay
> backlogged (`docs/BACKLOG.md`). This doc is the design record of what
> shipped: the implementation is `cazzubot/assets.py` + each plugin's
> `asset_decl`.

## Motivation

The frog economy grew from "catch a frog, consume for exp" into a
content-driven gamification system: **catchable frog species** with
**effects** (exp multipliers, …), and every one of those features needs
imagery — species art, badge art. Before this system, the bot had **no
asset management at all**: imagery was hardcoded external URLs and emoji
references in three different styles.

This doc defines the core asset system plugins opt into. It is deliberately
generic: the frog catalog (species, effects) is designed *alongside* it and
references it, but is a separate concern.

## Background — why this was needed (pre-implementation)

The gaps below motivated the system; the asset service closed them.

- All runtime imagery was **hardcoded external URLs** as module-level
  constants or inline literals: catbox.moe (`plugins/counter/extension.py:24-27`,
  `plugins/poll/extension.py:24-25`, `cazzubot/utils.py:72`), imgur
  (`plugins/frogs/extension.py:101,132`), Discord CDN emoji webp
  (`plugins/experience/extension.py:21-24`, `plugins/frogs/extension.py:29-32`).
- Emoji references were a mix of guild-emoji mention strings
  (`<:cirnoFrog:…>` in `plugins/frogs/factory.py:26-27`), unicode, and
  emoji-as-image URLs — three styles, none centrally managed.
- The asset dirs (`emojis/`, `board/`, `download/`) are gitignored
  leftovers and **never read by code**. Only `emojis/` is written, by a
  one-way owner scrape (`plugins/dev/__init__.py:70-83`); `board/` and
  `download/` have no writers at all. The inktober scraper writes to
  `downloads/` (plural) — a mismatch with the `download/` dir name
  (`plugins/fun/__init__.py:159`).
- The `Plugin` contract had no asset mechanism — no manifest, registry, or
  file-registration command existed.
- The message template pipeline is **URL-only**: `templates.prepare`/`send`
  deal in content/embeds only, and no code path produces a `discord.File`.

## Goals

1. One way to *get* an asset (declaration), one way to *reference* it
   (keyed lookup), one way to *verify* it (boot drift check) — replacing the
   scattered URL/emoji styles above.
2. **Code/data split for gamification:** species *effects* live in code;
   *which species exist and their art* are declared in code too (typed keys
   — the owner's choice), while the *bytes* ship as files on disk, swappable
   by redeploy.
3. **Atomic content drops:** seasonal themes, event frogs, shop rotations =
   "promote these keys" in one transaction (backlogged — needs the dynamic
   path).
4. **Nothing downstream changes:** delivery emits URLs, so templates, embeds,
   and the message pipeline keep working untouched.

## Non-goals

- Runtime hot-reload of bytes (boot-time sync is enough for a single guild).
- Per-user or per-guild asset variants (single-guild bot by design).
- Object storage (S3/R2) — Discord's CDN *is* the storage here; revisit only
  if the bot ever outgrows a single guild or needs serverless deploys.

## The three layers

### Layer 1 — Definition: where assets are declared

Two sources, same contract:

- **Static (bundled) — implemented:** the asset ships with the bot. Declared
  in plugin code as `asset_decl = {MyAsset: "assets/file.png"}`, where
  `MyAsset` is an enum whose members carry an `AssetSpec` (kind + path
  relative to the plugin folder). Lives in git, versioned with the code,
  changes via deploy.
- **Dynamic (runtime) — deferred:** an admin uploads bytes via a slash
  command (`asset add <key> <attachment>`). Lives in the registry + asset
  store, changes with no deploy. Backlogged; the static path covers today's
  needs.

Both produce the same thing: an entry `key → bytes + metadata`. Plugins never
care which source an asset came from — that's Layer 2's job.

### Layer 2 — Registry: the catalog

The registry is **one table — a catalog of records about assets**, not a
storage bin. Bytes always live on disk; a row describes one asset. A row is
created by the static path at boot (the dynamic path would create rows the
same way — same shape either way).

```sql
CREATE TABLE IF NOT EXISTS asset (
	key    TEXT PRIMARY KEY,   -- derived: "FrogAsset.LEAF_FROG"
	kind   TEXT NOT NULL,      -- AssetKind: "species" | ...
	sha256 TEXT NOT NULL,      -- content address of the bytes
	path   TEXT NOT NULL,      -- file under the owning plugin's folder
	url    TEXT                -- published Discord CDN URL (Layer 3)
)
```

- **Keys are derived and typed** — the registry key comes from the asset's
  enum identity (`asset_key(member)` → e.g. `FrogAsset.LEAF_FROG`), never a
  hand-written string. Code references assets *by enum member only* — never
  by path, string, or URL. That inversion is what lets you swap storage,
  swap art, and add variants without touching callers.
- **Content addressing** (sha256) is what makes everything else work:
  identical files dedupe, drift is detectable (file changed without being
  re-registered), and a new hash is a natural cache-buster.
- The design's `meta` column (jsonschema-validated annotations) was dropped
  from the shipped schema — add it back when a consumer actually reads it.

The registry is **plumbing, not a content authority** — it has no opinion
about what frogs are. It mirrors the existing shared services:

| Shared infrastructure | All plugins use it | Content stays per-plugin |
|---|---|---|
| `bot.db` | one sqlite file | each plugin owns its own tables |
| `bot.settings` | one JSON store | keys are namespaced: `frog.enabled` |
| `bot.assets` | one registry + one CDN sync | each plugin owns its own keys + files |

### Layer 3 — Delivery: how bytes reach Discord

The message pipeline is URL-only (a deliberate constraint). Instead of
fighting it with `discord.File`, the registry treats **Discord's CDN as the
asset host**:

- A sync step compares registry hashes against what's published; only **new
  or changed** blobs (sha256 diff) get uploaded — to a private asset channel
  — and the resulting stable CDN URL is stored in the row. Skipped with a
  boot warning when no asset channel is configured (`ASSET_CHANNEL_PROD`/`DEV`).
- At runtime, `bot.assets.get(member)` returns that URL, which flows straight
  into embeds and spawn messages — exactly like the old hardcoded URLs, just
  centrally managed.
- Discord does hosting, caching, animation, and delivery for free. Single
  guild = a private channel is a fine "bucket"; uploads only happen on
  content change, so rate limits are a non-issue.

## Lifecycle flows

### Boot reconcile (static assets)

1. Walk each plugin's `asset_decl` enum (the plugin list is the source of
   what exists — no central manifest).
2. For each: read the file, compute sha256.
3. Row missing or hash differs → upsert the row and queue the bytes for CDN
   upload (storing the returned URL).
4. Missing file on disk → `AssetError` → boot abort, mirroring
   `Database.verify_schema`'s fail-fast drift check.

For static assets the **file on disk is the source of truth**; the row is a
cached index of it. Edit the art and redeploy → boot notices, re-syncs.

### New frog species (code path)

Species are **code-defined** (`plugins/frogs/species.py`): write the species
dataclass (key, art enum member, catch/consume effect payloads) → restart →
boot registers the species + its assets and syncs the art → the spawn catalog
includes it. No data migration, no new columns.

### Admin upload (dynamic path) — backlogged

`asset add <key> <attachment>` → saves bytes into the owning plugin's
asset folder, computes sha256, inserts/updates the row, syncs to CDN. No
git, no deploy. Re-upload to the same key updates the row.

### Seasonal drop — backlogged

Scheduler-triggered "promote these keys" flips availability at the drop date;
shop and recipes see the new content without a deploy. One transaction, no
partial states.

## Ownership model

- **Segregated:** each plugin declares its own assets; files live inside the
  plugin folder (`plugins/frogs/assets/leaf_frog.png`), matching PLUGINS.md's
  "one feature = one folder". Dynamic uploads would land in the same folder
  for the plugin that owns the key. Assets version with plugin code,
  `/plugin reload` picks up changes, plugin removal takes its assets and rows
  with it.
- **Centralized (mechanism only):** the registry table and the CDN sync are
  shared — one schema, one private asset channel. The boot reconcile walks
  per-plugin declarations and *projects* them into the shared index; the
  registry is a projection, not the origin.
- **Enforcement (design):** because keys are derived from enum identity
  (`FrogAsset.LEAF_FROG`), ownership is structural — a plugin's declaration
  enum is all it can register. Namespaced admin keys (`frog.*`) were a
  design idea for the deferred dynamic path, not implemented.

## How the frog gamification landed

The asset system was designed to serve the frog catalog redesign. That
redesign shipped in a **code-first form** (the owner's choice — no
`frog_species` DB table):

- **Species are code-defined** (`plugins/frogs/species.py`): a `Species`
  dataclass carries `key: SpeciesKey`, `art: FrogAsset`, and the
  catch/consume effect payloads; `roll_species(rng)` does the weighted roll.
- **Effects** (`plugins/frogs/effects.py`): the `EffectKey` enum IS the
  effect registry, with a per-effect payload dataclass — no string-key →
  handler registration table, typed instead.
- **Inventory** (`member_frog.normal/frozen` columns) became the generic
  `bot.inventory` ledger: `frog:{species}:{state}` derived keys, where
  `FrogState` is NORMAL/FROZEN — "frozen" is an inventory state, exactly as
  the design intended.
- **Art** (`FrogAsset.LEAF_FROG` → `assets/leaf_frog.png`) is the
  `asset_decl` enum feeding the asset service.
- Shop, recipes/dishes, and seasonal drops remain backlogged
  (`docs/BACKLOG.md`).

## Open decisions

1. **Who can upload assets** (dynamic path): owner-only via admin commands
   vs. community submissions through a moderation queue. Deferred with the
   dynamic path.
2. **When to build the dynamic path:** the static-only path covers today's
   needs; build admin uploads when seasonal drops are real.

## Implementation status

Done: `Plugin.asset_decl` contract + `bot.assets` service (keyed lookup);
registry table + boot reconcile (static path, drift check); CDN sync to a
private asset channel (URL delivery). Backlogged: admin upload command +
`meta` schema (dynamic path); scheduler-driven promotion for seasonal drops;
shop/recipes.

## Relevant existing machinery

- `Plugin` contract: `cazzubot/plugin.py` (`name`, `extensions`, `schema`,
  `scheduled`, `asset_decl`, `depends_on`, `on_load`/`on_unload`).
- Asset service: `cazzubot/assets.py` (`Assets.reconcile` / `sync_cdn` /
  `get`, `asset_key`, `AssetSpec`, `AssetKind`).
- Boot drift check to mirror: `Database.verify_schema` (`cazzubot/db.py`).
- Template delivery to keep untouched: `cazzubot.templates` `prepare`/`send`.
