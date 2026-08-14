# CazzuBot — Asset Management (design)

> **Status:** design only, not implemented. Written from the gamification
> planning discussion (frog species, effects, shop, combining); parked in
> `docs/BACKLOG.md` for later review and potential implementation.

## Motivation

The frog economy is about to grow from "catch a frog, consume for exp" into a
content-driven gamification system: a **variety of catchable frog species**
with **effects** (exp multipliers, temporary rank rewards, …), a **shop**, and
**combining frogs into dishes** for consumption. Every one of those features
needs imagery — species art, dish art, shop icons, badge/tier art — and today
the bot has **no asset management at all**.

This doc defines a core asset system that plugins opt into. It is deliberately
generic: the frog catalog (species rows, effects, recipes, shop) is designed
*alongside* it and references it, but is a separate concern.

## Current state (why this is needed)

- All runtime imagery is **hardcoded external URLs** as module-level
  constants or inline literals: catbox.moe (`plugins/counter/cog.py:24-27`,
  `plugins/poll/cog.py:24-25`, `cazzubot/utils.py:72`), imgur
  (`plugins/frogs/cog.py:101,132`), Discord CDN emoji webp
  (`plugins/experience/cog.py:21-24`, `plugins/frogs/cog.py:29-32`).
- Emoji references are a mix of guild-emoji mention strings
  (`<:cirnoFrog:…>` in `plugins/frogs/factory.py:26-27`), unicode, and
  emoji-as-image URLs — three styles, none centrally managed.
- The asset dirs (`emojis/`, `board/`, `download/`) are gitignored
  leftovers and **never read by code**. Only `emojis/` is written, by a
  one-way owner scrape (`plugins/dev/__init__.py:70-83`); `board/` and
  `download/` have no writers at all. The inktober scraper writes to
  `downloads/` (plural) — a mismatch with the `download/` dir name
  (`plugins/fun/__init__.py:159`).
- The `Plugin` contract (`cazzubot/plugin.py`) has no asset/resource
  mechanism — no manifest, registry, or file-registration command exists.
- The message template pipeline is **URL-only**: `templates.prepare`/`send`
  deal in content/embeds only, and no code path produces a `discord.File`.
  (Attachments are schema-legal in message templates today — `maxContains: 0`
  without `contains` is a jsonschema no-op — but nothing exercises them, and
  `sticker_ids` are never set.)

## Goals

1. One way to *get* an asset (declaration), one way to *reference* it
   (keyed lookup), one way to *verify* it (boot drift check) — replacing the
   scattered URL/emoji styles above.
2. **Code/data split for gamification:** species *effects* live in code;
   *which species exist, their art, rarity, price, availability* live in data
   — swappable without deploys.
3. **Atomic content drops:** seasonal themes, event frogs, shop rotations =
   "promote these keys" in one transaction.
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

- **Static (bundled):** the asset ships with the bot. Declared in plugin
  code (a `Plugin.assets` field, or a species registration naming its art).
  Lives in git, versioned with the code, changes via deploy.
- **Dynamic (runtime):** an admin uploads bytes via a slash command
  (`asset add frog.species.leaf_frog <attachment>`). Lives in the registry
  + asset store, changes with no deploy.

Both produce the same thing: an entry `key → bytes + metadata`. Plugins never
care which source an asset came from — that's Layer 2's job.

### Layer 2 — Registry: the catalog

The registry is **one table — a catalog of records about assets**, not a
storage bin. Bytes always live on disk; a row describes one asset. A row is
created by either the static path (derived from a repo file at boot) or the
dynamic path (created with an uploaded file), but the row is the same shape
either way.

```sql
CREATE TABLE IF NOT EXISTS asset (
	key       TEXT PRIMARY KEY,          -- namespaced: frog.species.leaf_frog
	kind      TEXT NOT NULL,             -- species | dish | shop | badge | ...
	sha256    TEXT NOT NULL,             -- content address of the bytes
	path      TEXT NOT NULL,             -- file under the owning plugin's asset folder
	url       TEXT,                      -- published Discord CDN URL (Layer 3)
	meta      TEXT NOT NULL DEFAULT '{}' -- jsonschema-validated JSON
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
- `meta` (animated, rarity, credit, season, …) is jsonschema-validated — the
  `templates.verify` philosophy, so admins can't put garbage in.

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
  — and the resulting stable CDN URL is stored in the row.
- At runtime, `bot.assets.get(key)` returns that URL, which flows straight
  into embeds, spawn messages, shop icons, dishes — exactly like today's
  hardcoded URLs, just centrally managed.
- Discord does hosting, caching, animation, and delivery for free. Single
  guild = a private channel is a fine "bucket"; uploads only happen on
  content change, so rate limits are a non-issue.

## Lifecycle flows

### Boot reconcile (static assets)

1. Walk each plugin's declared assets (the plugin list is the source of what
   exists — no central manifest).
2. For each: read the file, compute sha256.
3. Row missing or hash differs → update the row and queue the bytes for CDN
   upload (storing the returned URL).
4. Verify every referenced key resolves. Any failure → abort boot, mirroring
   `Database.verify_schema`'s fail-fast drift check.

For static assets the **file on disk is the source of truth**; the row is a
cached index of it. Edit the art and redeploy → boot notices, re-syncs.
Delete a row and reboot → it re-derives.

### New frog species (code path)

You write the registration (effect handler + asset keys) → restart or
`c!cog reload frogs` → boot registers the species + its assets and syncs the
art → the spawn catalog includes it. No data migration, no new columns.

### Admin upload (dynamic path)

`asset add <key> <attachment>` → saves bytes into the owning plugin's
asset folder, computes sha256, inserts/updates the row, syncs to CDN. No
git, no deploy. Re-upload to the same key updates the row.

### Seasonal drop

Scheduler-triggered "promote these keys" flips availability at the drop date;
shop and recipes see the new content without a deploy. One transaction, no
partial states.

## Ownership model

- **Segregated:** each plugin declares its own assets; files live inside the
  plugin folder (`plugins/frogs/assets/leaf_frog.png`), matching PLUGINS.md's
  "one feature = one folder". Dynamic uploads land in the same folder for
  the plugin that owns the key's namespace (`frog.*` →
  `plugins/frogs/assets/`). Assets version with plugin code, `c!cog reload`
  picks up changes, plugin removal takes its assets and rows with it.
- **Centralized (mechanism only):** the registry table and the CDN sync are
  shared — one schema, one private asset channel. The boot reconcile walks
  per-plugin declarations and *projects* them into the shared index; the
  registry is a projection, not the origin.
- **Enforcement:** because keys are namespaced, the registry can enforce
  ownership — the frogs plugin can only register `frog.*`, ranks only
  `rank.*`. Admin uploads are above the rules.

## Relationship to the frog catalog redesign

The current frog model is **columns per type** (`member_frog.normal/frozen`,
`FrogTypeEnum` = NORMAL/FROZEN, hardcoded `_EXP_PER_FROG` in
`plugins/frogs/logic.py:15-17`) — incompatible with "variety of frogs added
on the fly". That schema change is the *prerequisite*; asset management is
designed to serve it:

- `frog_species` catalog table — one row per species:
  `key, name, rarity, description, effect_key, spawn_weight, price, asset_key`
- `member_frog_inventory(uid, species_key, qty)` — replaces the columns
- `frog_recipe(key, inputs JSON, output_species_key)` — a dish is just a
  species-like row whose source is crafting, not capture
- A **shop** is catalog views over the same rows
- "Frozen" becomes a per-season inventory *state*, not a species
- **Effects** reuse the existing string-key → handler pattern
  (`Plugin.scheduled`, the scheduler): an effect registry
  (`register_effect("buff.exp", ExpBuffEffect(...))`); species rows reference
  `effect_key`; time-boxed effects map onto `bot.scheduler.add(...)`.

Asset keys follow: `frog.species.leaf_frog`, `frog.dish.stew`,
`frog.shop.icon.leaf_frog`, `rank.badge.cirno`. (The implemented registry
derives keys from enum identity instead — see `docs/ROADMAP.md` Phase 1;
the dotted names here are the conceptual namespace, not literals.)

## Open decisions (not blocking the doc)

1. **Catalog source:** species defined in code registrations (auto-insert
   catalog rows) vs. Discord-added vs. both. The hybrid works for all three;
   the schema supports each, so nothing here locks it in.
2. **Who can upload assets:** owner-only via admin commands vs. community
   submissions through a moderation queue (a whole feature on its own).
3. **When to build the dynamic path:** start with static-only (Layer 1 +
   boot reconcile), add admin uploads when seasonal drops are real.

## Suggested implementation order

1. `Plugin.assets` contract + `bot.assets` service (keyed lookup).
2. Registry table + boot reconcile (static path, drift check).
3. CDN sync to a private asset channel (URL delivery).
4. Frog catalog rework (species/inventory/recipe tables) — depends on 1–3.
5. Admin upload command + `meta` schema (dynamic path).
6. Scheduler-driven promotion for seasonal drops.

## Relevant existing machinery

- `Plugin` contract: `cazzubot/plugin.py` (`name`, `cogs`, `schema`,
  `scheduled`, `on_load`/`on_unload`) — assets would be a sibling field.
- Boot drift check to mirror: `Database.verify_schema` (`cazzubot/db.py`).
- Message JSON validation to mirror for `meta`:
  `cazzubot.templates.verify` (jsonschema).
- Template delivery to keep untouched: `cazzubot.templates` `prepare`/`send`.
- Settings namespace convention: `cazzubot/settings.py`.
