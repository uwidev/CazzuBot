# Backlog

Deferred work, parked by request ("we will work on it later when I request it").
Pick these up when the owner asks; each item links to the discussion that
motivated it. Completed items are archived in `docs/DONE.md`.

## `bot.get_plugin(name)` + optional-dependency degrade

Public accessor for loaded plugins (today callers reach into
`bot._plugin_by_name`, e.g. `plugins/dev/__init__.py`). Plus a degrade pattern
for optional dependencies: if a dependency is unloaded/hotswapped, dependents
skip their call instead of crashing.

## Core event bus — `bot.events`

`emit`/`on`/`off` for bot-specific events (`member_leveled_up`,
`frog_captured`, …) so producers never know their consumers. Design decision
already made: the bus lives in **core** (`cazzubot/events.py`) — a generic
capability, not feature logic. Caveat to respect: events are less traceable
than direct calls and ordering isn't guaranteed — reach for them only when the
producer shouldn't know the consumer exists.

## Event-bus consumer demo

One real consumer (e.g. a "level-up milestone" channel) to validate the bus
design before wider adoption.

## Core asset management (design in docs/ASSETS.md)

Full design written up in `docs/ASSETS.md` from the gamification planning
discussion — parked here for later review and potential implementation. The
short version: a three-layer system — plugin-declared definitions (static in
git / dynamic via admin upload), a content-addressed registry table (catalog
of records, namespaced keys), and Discord-CDN delivery (sha256-diffed sync to
a private asset channel, URL-only so templates/embeds stay untouched).
Prerequisite (also designed there): the frogs catalog rework — species rows +
inventory + recipes replace the current column-per-type model
(`member_frog.normal/frozen`, `FrogTypeEnum`), with effects via a
string-key → handler registry and dishes as crafted species.

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

**Core DONE (2026-08-09):** `plugins/board/` — `/board scrape [channel]
[week]` collects a week's image attachments (static only — animated
uploads are skipped by frame count; content-hash dedup within the week)
into a `board` table row per image (`ts` ISO-8601 UTC, `image_url` CDN
url, `msg_url` message link, `sha256`), defaulting to last week (this
week − 1); `/board post [columns] [cell_size]` stitches the most recent
week's rows into a numbered grid (the `stich.py` script, absorbed as
`plugins/board/stitcher.py`; defaults 9 cols / 768px cells, adjustable),
pruning rows whose image no longer downloads (message deleted), and posts
the grid with per-image message links in an embed. `plugins/misc/` holds
the server utilities split out of the original plan: `/misc banner
[image] [msg]` (16:9 guild banner, or from the first image attachment of
a message link), `/misc welcome` (API-editable parts — the welcome-screen
*background image* is client-side only and cannot be set via the API),
and `/misc week [start] [msg]` (current week with Sunday/Monday start, or
a message link placed in its week via snowflake decoding; the shared week
math lives in `cazzubot.utils`).

Remaining — the weekly automation, implemented as code (the generic
pipeline engine was decided against 2026-08-13; see docs/DONE.md):

- Scheduled flow: a `weekly` scheduler tag (`At(weekday=(6,), time="00:00")`,
  mirroring `plugins/daily/__init__.py`, catch-up on boot for weeks missed
  while down) whose handler calls the board + poll service functions
  directly: scrape the just-ended week, post the grid, register the poll
  and open voting (24h, closing end of Sunday).
- Service extraction (prerequisite): `Scrape.invoke`/`Post.invoke` in
  `plugins/board/cog.py` are thick controllers — move the history walk,
  dedup, prune and stitch orchestration into `plugins/board/logic.py`
  service functions (test-first, per the CSR loop); extract the poll
  `Send` embed+button construction into a shared helper so the scheduled
  handler can send via `bot.rest`.
- Poll tie-in: the grid message carries a `poll:vote:<pid>` button; the
  poll plugin's modal voting (items = grid numbers, `max_vote=1`).
- Winner flow: at close, pick the highest-voted image, set it as the guild
  banner (16:9 prep via `plugins/misc.logic.prepare_banner`), and
  announce the winner with a link to the original message.

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
