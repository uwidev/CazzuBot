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

## Fold the `daily`/`quarterly` scheduler plugins into their owning plugins

`plugins/daily/` and `plugins/quarterly/` are scheduler-only wrappers that
own no data: `daily`'s `reset()` runs experience resets
(`exp_db.reset_all_msg_cnt`, `reset_all_cdr`, `sync_with_exp_logs`) plus a
frog sync (`frog_db.sync_with_frog_logs`), and `quarterly`'s `reset()` is
entirely `frog_db.freeze_frogs`. The cadences should live with the work —
move the scheduled handlers and `on_load` arming into `plugins/experience/`
and `plugins/frogs/` and delete the two wrapper folders. Watch the one
structural wrinkle: the scheduler keys tags by name, so the two halves of
the midnight reset need distinct tags (e.g. `daily.exp`/`daily.frog`) or a
shared orchestrator — pick whichever keeps the retry semantics intact.

## Welcome "Unknown User" mention — users-cache race

The welcome message's `{mention}` placeholder occasionally renders as
"Unknown User" in Discord: the `<@id>` mention is resolved through the
users cache, and a member who just finished onboarding may not be in it
yet when the welcome is sent. `_send_welcome` already sleeps a fixed 1s
("let user UI update so the ping works") — insufficient, and it's not
clear whether the stale cache is the bot's or Discord's own. Fix ideas to
investigate: wait (poll with timeout) until `bot.cache.get_member` returns
the member before sending, or add a longer/retrying delay; first figure
out which cache actually fails to be populated in time.
