# Backlog

Deferred work, parked by request ("we will work on it later when I request it").
Pick these up when the owner asks; each item links to the discussion that
motivated it. Completed items are archived in `docs/DONE.md`.

## dev friendly timestamp to sqlite compatible format time
Right now, this is how it looks to add a timestamp to the database.

> pendulum.now("UTC").to_iso8601_string()

Looks very ugly, and doesn't really hint "use this to encode to sqlite friendly time". Either refactor or rename, something so it reads more elegantly.

## bot.settings, surely there's more elegant way...
This was originally some per-guild settings key:value pair. But now that gid's are no more, this now exists as, well, the bot settings on how to do specific operations that can be configured at runtime on the admin side.

In practice, as a one-guild specialization, this seems to(?) create some odd friction when developing, as I have to consider if a setting is something that needs to be dynamically set at runtime rather than mostly set in stone.

For example, most if not all messages are more-or-less locked in stone for now. If I ever change it, it would probably best be done through code, not through some json file.

Enabling/disabling frog spawns... probably fine. Need a full review of this.

## Game features — the app is becoming a game

Design discussion (2026-08): the bot has evolved into a casual
collection/progression game hosted in Discord (message exp → levels/ranks,
frog capture → inventory, consume = the exp sink, quarterly freeze = the
seasonal soft reset). The systems below were scoped in that discussion; the
shared substrate (generic `inventory` + `member_effect` stores, typed
keys, `bot.events`) is built first. Member-state design decision recorded:
**no central member row** — scalar per-feature state lives in narrow
per-feature tables, shapes that repeat across features earn a generic
store, history stays in append-only logs, and the "whole member" is a
derived profile view composed on read (never stored).

### Badge / achievement system (earned)

The event bus's first real consumer demo. Badge definitions in code (like
species), a **trigger registry reusing the effects convention**
(`TriggerKey` enum → typed config → predicate) over `bot.events` (and
gateway events for message-content triggers), and a
`member_badge(uid, badge_key, earned_at)` table — **earned** records
(criteria-based, one-time), distinct from owned vanity items below.

### Vanity collectables (owned)

Pins/frames/titles as **inventory items** — the generic `inventory` store

- typed keys + assets for art + a display/equip mechanism. **Owned**
  (countable, tradeable later). The earned-vs-owned split is the design
  principle: achievements record, inventory owns.

### Classes / activity tracks / professions

A **track** = per-activity progression (uniform xp/level/leaderboard per
activity — the message-exp pattern generalized). Frog catcher ↔ capture
track, alchemist ↔ combine track, etc. A `member_track(uid, track_key, xp)`
table only once a second track exists (first track can be a narrow
per-feature table); a "class" = a named track bundle; role-bound variants
need no table (derived from roles). Hard RPG classes (exclusive abilities,
per-class leveling) are out of scope.

### Combining / recipes (chef · alchemist)

Code-defined **recipe registry** (inputs `{species: qty}` → output
species) — "a dish is just a crafted species" (roadmap). Combine = the
inventory ledger as the mechanism (consume input stacks, grant the output)
— a new economy sink; the alchemist profession is the combine track.

### `/inventory consume` — **DONE (2026-08-19); the emoji glyphs remain**

The index-based `/inventory consume (INDEX) [AMOUNT]` half is **done and
archived** (see `docs/DONE.md`): it replaces `/frog consume` — `INDEX`
resolves through the derived `bot.inventory.rows_indexed` slots, then runs
the item's **item-owned** consume and decrements the stack (item-vs-entity
model + "deprecate behavior, keep items" story in `docs/ITEMS.md`).
`/inventory` is now a group (`/inventory view`, `/inventory consume`) and
rides on `bot.items`, not the old renderer registry (removed as redundant;
unresolved ids are hidden in the grid).

Still open: **real per-species emoji glyphs** for the frog *items* (and the
`/inventory` grid + `/frog catalog` that render them) — declared as
`AssetKind.EMOJI` in the asset child-guild instead of the current 🐸
placeholder. The emoji-kind asset sync is built (`docs/ASSETS.md`); what's
left is declaring and publishing per-species glyphs and pointing the item
icons at them.

### Game-patterns lexicon (docs)

Name the patterns and map each to its code home so "new feature" = "which
pattern is this?": loot tables → `roll_species`, inventory ledger →
`inventory`, buffs/modifiers → `member_effect`, seasonal resets →
quarterly, achievements → badges, event spine → `bot.events`, faucets /
sinks → capture / consume. Include the emergent-dynamics vocabulary
(hold-vs-spend, conversion + decay, the daily/weekly/quarterly tempo
layers). The **entity↔item lexicon and the two-flag "deprecate behavior,
keep items" story** now live in `docs/ITEMS.md` (entity = world/spawn
object with behavior; item = ledger object with an immutable `item_id`
oracle and item-owned consume; `enabled` gates behavior while
`items_consumable` gates consumption, independently).

## Self-documenting / low-friction sweep

Per the design principles in `AGENTS.md`: sweep the codebase so it conforms
to (1) **self-documenting code** — where the call graph is ambiguous, add a
comment naming the caller/emitter/subscriber at the point of ambiguity
(who calls this method, who emits this event, who invokes this handler,
who consumes these rows), so a reader never has to hunt for "what pulls
this"; and (2) **minimum friction to build on** — spot-check that
infrastructure shapes don't force awkward workarounds on their consumers
(isolation/atomicity/modularity kept, no needless indirection). The event
system is the annotated reference case: `cazzubot/events.py` states who
calls `on`/`emit`, `plugins/frogs/events.py` names the sole emitter of
each event, and the emit call sites in `factory.py`/`extension.py` state the
same. Extend that pattern to the rest of the codebase (scheduler
handlers, service entry points, listeners, template formatters).

## `bot.get_plugin(name)` + optional-dependency degrade

Public accessor for loaded plugins (today callers reach into
`bot._plugin_by_name`, e.g. `plugins/dev/__init__.py`). Plus a degrade pattern
for optional dependencies: if a dependency is unloaded/hotswapped, dependents
skip their call instead of crashing.

## Core event bus — `bot.events`

**IMPLEMENTED (2026-08-14)** — `cazzubot/events.py`: typed `emit`/`on`,
subscribers awaited in registration order with failures isolated (an
observer can never break the emitter). The frogs plugin emits
`FrogCapturedEvent`/`FrogConsumedEvent` after its transactional work. The
bus is for **observations** only; entity-bound behavior (species effects)
stays inline with the flow that owns the entity.

## Event-bus consumer demo

One real consumer to validate the bus end-to-end. The planned badge /
achievement system is the natural candidate — its triggers subscribe to
the bus (and gateway events) exactly like the effects registry's
enum-key → typed-config → handler convention, over events instead of
species fields.

## Core asset management (design in docs/ASSETS.md)

Full design written up in `docs/ASSETS.md` from the gamification planning
discussion — parked here for later review and potential implementation.
The static half is implemented (2026-08-14): `Plugin.assets` declarations,
the content-addressed registry, boot reconcile, and CDN sync to a private
asset channel (the dynamic admin-upload path stays deferred).

## Run the bot via a [project.scripts] entry

`main.py` is run as `uv run python main.py [-d|-p|-s]`. Add a
console-script entry (e.g. `cazzubot = "…:main"`) so the bot runs as
`uv run cazzubot -d`, consistent with the `cazzubot-cli` entry added for
the role CLI. Requires moving main()'s logic into the package (e.g.
`cazzubot/__main__.py` or a small run module) so it is importable as a
script target; keep the existing `python main.py` path working.

## Mod plugin — deferred, in development (manual test backlog)

Manual testing of the whole `mod` feature (warn/mute/kick/ban/unmute/unban/
set/slowmode) is parked by the owner: it is not core, not finalized, and
"in progress" in terms of development. The E1–E5 items in
`docs/MANUAL_TEST.md` stay untested until the feature is declared done.
(Fixed along the way: the `mod set` group was defined but never registered
— `loader.command(mod_set)` was missing, so `/mod set` didn't exist.)

## Resync command UX — long ops after a confirm click

`exp resync` and `frog resync` confirm with a Yes/No menu, then run a long
DB rebuild. The click is now properly acked (menu fix, 2026-08-08), but the
owner wants a better flow than "click Yes, prompt vanishes, a few status
followups, done" — ideas to evaluate later: defer with a progress message
that gets edited as phases complete, or a single final summary edit.
Owner's words: "I think optimally we want better UX here. Will think of a
proper flow later. Backlog this."

## Board plugin — weekly image scrape + numbered grid

**Core DONE (2026-08-09):** `plugins/board/` — `/board scrape [channel] [week]` collects a week's image attachments (static only — animated
uploads are skipped by frame count; content-hash dedup within the week)
into a `board` table row per image (`ts` ISO-8601 UTC, `image_url` CDN
url, `msg_url` message link, `sha256`), defaulting to last week (this
week − 1); `/board post [columns] [cell_size]` stitches the most recent
week's rows into a numbered grid (the `stich.py` script, absorbed as
`plugins/board/stitcher.py`; defaults 9 cols / 768px cells, adjustable),
pruning rows whose image no longer downloads (message deleted), and posts
the grid with per-image message links in an embed. `plugins/misc/` holds
the server utilities split out of the original plan: `/misc banner [image] [msg]` (16:9 guild banner, or from the first image attachment of
a message link), `/misc welcome` (API-editable parts — the welcome-screen
*background image* is client-side only and cannot be set via the API),
and `/misc week [start] [msg]` (current week with Sunday/Monday start, or
a message link placed in its week via snowflake decoding; the shared week
math lives in `cazzubot.utils`).

**Weekly automation DONE (2026-08-13):** the `board_weekly` scheduler tag
(`At(weekday=(6,), time="00:00")` — Sunday 00:00 UTC, catch-up on boot
for weeks missed while down) runs the scrape → poll → grid flow every
Sunday: scrape the just-ended week (production = last week via
`SCRAPE_CHANNEL_PROD`, development guild = current week via
`SCRAPE_CHANNEL_DEV`; targets picked by `Config.guild_kind`, the
`.env`-loaded guild side), register + open a poll ("Week X of just-cirno
Voting", `max_vote = n // 20 + 1`, items = grid cells — a random sample
of 50 when a week overflows MAX_IMAGES), then sends ONE combined message:
role-ping "voting has opened" announcement (`MESSAGE_OPEN` →
`<@&VOTE_ROLE_ID>`) + numbered grid links in the content, the stitched
grid as the attachment, and the poll embed + vote button as the
embed/component — all in `POST_CHANNEL_*`. A `board.weekly.done` settings
claim-guard makes
retries safe, and `/board weekly` (owner) runs the flow manually
(`force=True`, bypassing the guard) for testing. The service extraction
prerequisite was folded in: `logic.scrape_week`/`logic.build_grid` are
shared by the commands and the automation, and `poll`'s embed+button
construction is the shared `build_send_payload`.

Remaining — none for the weekly pipeline: the close + winner flow is
implemented too (2026-08-13):

- Every weekly poll auto-closes 24h after opening (a `board_weekly_close`
  scheduler row → Monday 00:00 UTC). Closing removes the vote button and
  the vote flow refuses closed polls; `/poll open`/`/poll close` sync the
  button on the poll's message. The poll table stores the message's
  channel (`cid`) for that — migrated by `scripts/migrate_poll_cid.py`
  (run while the bot is stopped, before booting the new code).
- At close, the highest-voted image becomes the guild banner (16:9 prep
  via `plugins/misc.logic.prepare_banner`) and a winner announcement with
  the original message link is posted in the poll channel; a no-votes
  week just announces that (no banner change).

## Document how to add a test for a feature

A step-by-step how-to in the docs: where per-feature tests live
(`tests/plugins/<feature>/`), the test-first rule (pin behavior at the
highest layer that can express it), how to fake the framework surface
(`tests/fakes.py`, `FakeContext`, `invoke_command`), when a layer-1 unit
test suffices vs the offline interaction driver (`tests/driver.py`
`run_slash`/`press_button`/`submit_modal`), and how to run the suite
(`uv run pytest`). `docs/TESTING.md` covers the *strategy* and layers; the
"add a test for your new feature" recipe is what's missing.

## Document how hikari works

Developer-facing doc on the framework itself: gateway vs REST, the event
system (listeners, `event_factory` deserialization, the event manager),
caches, components (buttons/menus/modals), and how lightbulb layers on
(loader, commands, checks, error handling) — enough that a contributor
new to hikari can orient without reading upstream docs cover-to-cover.
The existing hikari documentation may already be enough; the work is to
read it and distill what's relevant here (`docs/HIKARI_MIGRATION.md` has
the port-time notes).

## ~~Fold the `daily`/`quarterly` scheduler plugins into their owning plugins~~ — DONE (2026-08-14)

Moved to `docs/DONE.md`: the wrapper plugins are deleted; the `daily` reset
lives in experience and the `daily.frog` resync + `quarterly` freeze live
in frogs, each armed by its owning plugin's `on_load`.
