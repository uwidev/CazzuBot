User command guide
==================

Commands for the three member-facing systems: **exp profile**, **inventory**,
and **frog spawning**. Every command is a guild-scoped slash command. Admin
and owner commands are marked `[Admin]` / `[Owner]` and summarized at the end;
the rest are available to everyone. Times are UTC.


At a glance
-----------

| Command | What it does |
| --- | --- |
| `/experience view [user] [mode]` | Membership card: rank, level, exp, percentile (`seasonal` default, or `lifetime`) |
| `/experience leaderboard [year] [season] [page]` | Paged seasonal exp leaderboard (button-paged) |
| `/inventory view [user]` | A member's numbered inventory grid |
| `/inventory info <slot>` | An item's description card (from a slot you own) |
| `/inventory consume <slot> [amount]` | Consume an item for its outcome (with confirm) |
| `/frog catalog` | All catchable frog species that spawn |
| `/frog profile [member]` | This season's frog capture permit |
| `/frog lifetime [user]` | All-time frog capture permit |


1. Exp profile
--------------

Exp is earned by chatting. Each of your messages grants exp after a **15-second
cooldown**; the first message of the day is worth **20 exp**, decaying
quadratically to **1 exp** by your 77th message, where it stays for the rest
of the day. At 00:00 UTC the message counter resets and the cooldown clears,
so the daily curve starts over.

Levels are computed from exp via a wavy curve — each level needs more exp than
the last on average, with gentle dips and rises along the way. Seasons are
quarters (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec); seasonal totals reset at the
start of each quarter, lifetime totals never do. Rank roles are granted
automatically at level thresholds (configured per season and for lifetime) and
show up on the card as your rank.

 -  `/experience view [user] [mode]` — your membership card: current rank
    role, level, exp, your percentile among all members, and your place in
    the scoreboard. `mode` picks the window, `seasonal` (default) or
    `lifetime`; defaults to you, pass a user to look at theirs.
 -  `/experience leaderboard [year] [season] [page]` — the seasonal
    leaderboard, 10 entries per page, your row highlighted. The buttons
    below the embed page through the board: ◀/▶ change page, ⬅/➡ jump whole
    seasons. Only the invoker may click them, and they expire after 30
    seconds.

Members with no exp yet get a card that says so — nobody starts at rank 0.


2. Inventory
------------

Every member has an inventory ledger of item stacks. Slots are derived, not
stored: your stacks are numbered in a fixed item order, grouped by item type,
so slot numbers always address the same item in every command.

 -  `/inventory view [user]` — a numbered grid of the member's stacks, each
    with its quantity (e.g. `1 🐸 ×3`). Empty inventories say so. Defaults to
    you.
 -  `/inventory info <slot>` — the item in that slot of *your* inventory as a
    description card: art thumbnail, name, description, and labeled fields
    such as "On consumption". You can only inspect items you own.
 -  `/inventory consume <slot> [amount]` — consume one or more of an item from
    *your* inventory. A confirmation menu shows the before/after quantity
    (120-second timeout). The item's own effect runs first — a failed outcome
    never eats your items — and the stack is decremented only after it
    succeeds. You cannot consume items that have no consume behavior, or more
    than you hold.

Frog items grant exp and a small status effect on consume. Values below are
the code defaults; the live numbers always show in `/frog catalog`:

| Item | Exp | On consumption |
| --- | --- | --- |
| Basic Frog | 10 | nothing further |
| Pog Frog | 30 | 1% chance the bot reacts to your messages with the froggers emoji, 1 hour |
| Froggers Frog | 300 | 7% chance of the reaction above, 1 hour |
| Classy Frog | 200 | the **Classy** role for 3 hours |

Re-consuming the same item while its status is active extends the duration
rather than stacking a stronger effect.


3. Frog spawning
----------------

Frogs spawn into admin-registered text channels on a **chaotic timeline**:
each spawn fires `interval` after the previous one, jittered by `fuzzy` (e.g.
a 30-minute interval at 50% fuzziness waits between 15 and 45 minutes). The
next spawn is scheduled from the previous fire regardless of how this frog
turns out, so frogs can overlap and nobody can time the schedule.

The visible frog is always one of the catchable species, rolled by weight —
Basic Frogs are the most common and Froggers Frogs the rarest. The frog's
message shows its art and a Catch button, and it stays for `persist` seconds
(default 30, admin-configured 3–120). The **first click wins**: catching hands
you one of the species' item and announces it with your new totals; if nobody
catches it in time the frog gets bored and the message disappears. Either way
the message is deleted.

 -  `/frog catalog` — every catchable species with its name, art, and
    description. What catching or consuming a frog does is not part of the
    catalog — an item's own effects live on its `/inventory info` card.
 -  `/frog profile [member]` — your seasonal capture permit: total captures,
    rank and percentile, plus a per-species breakdown of the frogs you hold
    (normal vs frozen). Defaults to you.
 -  `/frog lifetime [user]` — the same permit against all-time totals.

**The quarterly freeze.** On the 1st of Jan/Apr/Jul/Oct at 00:00 UTC every
frog in the server folds down: all non-Basic frogs (normal *and* frozen)
become Basic Frogs, and those Basic Frogs freeze — after the reset everyone
holds only Frozen Basic Frogs, worth 3 exp instead of 10. It is a deliberate
"use it or lose it" reset: species identity and buffs do not carry over to
the next season. Frozen frogs are permanently worth less exp, which is why
you should consume your catches before the rollover.


4. Admin & owner commands
-------------------------

These configure the systems above; most members will never see them.

 -  **Exp** — `/experience quiet list|add|del` `[Admin]` suppress level-up
    messages in a channel; `/experience resync` `[Owner]` rebuilds lifetime
    exp from the logs.
 -  **Rank & level config** — `/level set|demo|raw` and
    `/rank add|remove|clean|clear|set …|demo|raw` `[Admin]` manage the
    rank-role thresholds and the level-up/rank-up message templates.
 -  **Frog spawning** `[Admin]`:
    -  `/frog register <interval> [persist] [fuzzy] [channel]` — make a
       channel a spawn channel. `interval` is a natural duration (production
       enforces ≥ 60s), `persist` seconds a frog lingers (3–120), `fuzzy`
       spawn-timing randomness (0–1), default channel is the current one.
    -  `/frog set enabled <true|false>` — turn spawning on or off for all
       registered channels (re-queues or clears the spawn schedule).
    -  `/frog set message <json>`, `/frog demo`, `/frog raw` — manage the
       capture-message template (placeholder-driven JSON).
    -  `/frog clear` — remove every spawn channel config and stop spawning.
 -  **Frog spawning** `[Owner]` — `/frog spawn [species]` force-spawns a frog
    in the current channel and `/frog fake [species]` posts one with its
    capture button (both for testing); `/frog resync` rebuilds lifetime
    captures from the logs.