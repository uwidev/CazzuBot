User command guide
==================

Commands for the three member-facing systems: **exp profile**, **inventory**,
and **frog spawning**. Every command is a guild-scoped slash command. Admin
and owner commands are marked `[Admin]` / `[Owner]` and summarized at the end;
the rest are available to everyone. Times are UTC.


At a glance
-----------

| Command                                          | What it does                                                                      |
| ------------------------------------------------ | --------------------------------------------------------------------------------- |
| `/experience view [user] [mode]`                 | Membership card: rank, level, exp, percentile (`seasonal` default, or `lifetime`) |
| `/experience leaderboard [year] [season] [page]` | Paged seasonal exp leaderboard (button-paged)                                     |
| `/inventory view [user]`                         | A member's numbered inventory grid                                                |
| `/inventory info <slot>`                         | An item's description card (from a slot you own)                                  |
| `/inventory consume <slot> [amount]`             | Consume an item for its outcome (with confirm)                                    |
| `/inventory thaw <slot> [amount]`                | Gamble a frozen frog back to life (50/50 per unit)                                |
| `/frog catalog`                                  | Your discovered frog collection (uncaught frogs show as silhouettes)              |
| `/frog view [member] [mode]`                     | Frog capture permit (`seasonal` default, or `lifetime`)                           |

1.  Exp profile

   - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

Exp is earned by chatting, and by nothing else — no item grants exp, so the
frog side never feeds this ladder. Each of your messages grants exp after a
**15-second cooldown**; the first message of the day is worth **20 exp**,
decaying quadratically to **1 exp** by your 77th message, where it stays for
the rest of the day. At 00:00 UTC the message counter resets and the cooldown
clears, so the daily curve starts over.

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

1.  Inventory

   - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

Every member has an inventory ledger of item stacks. Slots are derived, not
stored: stacks are numbered over what is actually visible — live items first by
quantity descending (largest stacks first), frozen frog trophies last — so slot
numbers always address the same item in every command, with no gaps.

 -  `/inventory view [user]` — a numbered grid of the member's stacks, each
    with its quantity (e.g. `[ 1 ] 🐸 ×3`). Empty inventories say so. Defaults
    to you. The grid pages through with ◀/▶ buttons when a member holds more
    than 25 distinct items.
 -  `/inventory info <slot>` — the item in that slot of *your* inventory as a
    description card: art thumbnail, name, description, and labeled fields
    such as “On consumption”. You can only inspect items you own.
 -  `/inventory consume <slot> [amount]` — consume one or more of an item from
    *your* inventory. A confirmation menu shows the before/after quantity
    (120-second timeout). The item's own effect runs first — a failed outcome
    never eats your items — and the stack is decremented only after it
    succeeds. You cannot consume items that have no consume behavior, or more
    than you hold.
 -  `/inventory thaw <slot> [amount]` — gamble frozen frogs (see the quarterly
    freeze below). Rolls per unit: 50% restores the species' normal frog, 50%
    leaves Frog Remains.

Consuming a frog grants its status effect and nothing else — no exp. An
item's own live effects show on its `/inventory info` card:

| Item          | On consumption                                                            |
| ------------- | ------------------------------------------------------------------------- |
| Basic Frog    | nothing — consuming it grants nothing                                     |
| Pog Frog      | 1% chance the bot reacts to your messages with the froggers emoji, 1 hour |
| Froggers Frog | 7% chance of the reaction above, 1 hour                                   |
| Classy Frog   | the **Classy** role for 3 hours                                           |
| Frog Remains  | nothing — a memorial, and only comes from a failed thaw                   |

Re-consuming the same item while its status is active extends the duration
rather than stacking a stronger effect. Frozen frogs are the exception: they are
trophies and cannot be consumed at all — see the quarterly freeze below.

1.  Frog spawning

   - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

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

 -  `/frog catalog` — your collection book: the species you have ever caught,
    each with its name, art, and description. Frogs you have not caught yet
    show as unnamed silhouettes, and some frogs stay out of the book
    altogether. Discovery is permanent — a species stays discovered after the
    quarterly freeze and after you consume it — and the book never lists
    rarity, exp, or weights. What catching or consuming a frog does is not
    part of the catalog — an item's own effects live on its
    `/inventory info` card.
 -  `/frog view [member] [mode]` — your capture permit: total captures, rank
    and percentile, plus an Inventory snippet of the frogs you currently hold.
    The snippet lists season-active (normal) frogs only, one icon per stack,
    smallest stack first; frozen trophies stay out of it. `mode` picks the
    window, `seasonal` (default) or `lifetime`; defaults to you, pass a member
    to look at theirs.

**The quarterly freeze.** On the 1st of Jan/Apr/Jul/Oct at 00:00 UTC every frog
in the server freezes **in place**: each species' normal stack becomes that
species' frozen stack, merging into whatever you already hold frozen. Species
identity survives the rollover — the frog's value does not.

Frozen frogs are trophies: they cannot be consumed, and their only use is the
thaw gamble.

 -  `/inventory thaw <slot> [amount]` — rolls **per unit**. Success (50%)
    restores the species' normal frog, with its status effect; it freezes
    again at the next rollover if you still haven't consumed it. Failure (50%)
    leaves **Frog Remains**, a memorial item that grants nothing.
 -  Cluster Frogs have no item, so nothing freezes for them. Frog Remains is
    not a frog — it never freezes and never thaws.

The rule of thumb: consume what you want before the rollover, or gamble on the
thaw after.

1.  Admin & owner commands

   - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

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
     -  `/frog clear` — remove every spawn channel config and stop spawning.
     -  `/frog_catalog` — render the full species set, including frogs that stay
        out of a member's book. Hidden from members; staff use it to check that
        every species' art renders.
 -  **Frog spawning** `[Owner]` — `/frog spawn [species]` force-spawns a frog
    in the current channel; `/frog resync` rebuilds lifetime captures from the
    logs; `/frog debug freeze <member>` runs the quarterly rollover for one
    member so the frozen state can be inspected before the real reset.
 -  The capture announcement is hardcoded now — there is no message template to
    configure.
