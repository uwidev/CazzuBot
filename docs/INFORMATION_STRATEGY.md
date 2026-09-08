Information strategy
====================

What player-facing text is allowed to say, and where. This doc governs every
surface a member can read: announcements, command descriptions, embeds, item
cards, footer tips. The bot complements chat and stays in the background
(`AGENTS.md`); the frog systems themselves are in `docs/FROG.md`.

The rule in one line: **say what an effect does and roughly how often, never how
much — and put the numbers only where a player has deliberately asked for
them.**


Why
---

The bot is not the game. It complements a conversation server: the primary
activity is talking to people, and these systems exist to make that talking more
playful. A system that can be solved — where one choice is strictly better than
another — stops being play and becomes a chore, and the community then polices
the deviation.

The distinction that matters is **dominance, not choice**. Choosing whether to
participate is still a choice, but it has no better answer; a choice with no
dominant option is expression. A published magnitude does not create a dominant
*play*, but it does create a dominant *valuation* — and a dominant valuation is
what turns a collection into a ranking. Information is the surface where that
happens, so this policy is about which number goes where, not about hiding
things.


The four properties
-------------------

Every described effect has four independent properties. “Concrete or vague” is a
dial on each one, not on the description as a whole:

 -  `Kind` — what happens (“the bot reacts to your messages”)
 -  `Rate` — how often it happens (“now and then”, “often”)
 -  `Magnitude` — how much it is worth
 -  `Conditions` — what gates it (duration, cooldown, state)

| Property   | Broadcast | Reference | Opt-in card | Commitment                     |
| ---------- | --------- | --------- | ----------- | ------------------------------ |
| Kind       | concrete  | concrete  | concrete    | concrete                       |
| Rate       | ordinal   | ordinal   | exact       | exact when it gates the action |
| Magnitude  | silent    | allowed   | exact       | exact                          |
| Conditions | silent    | allowed   | exact       | exact                          |


Surfaces
--------

Ordered from “everyone sees it, nobody asked” to “the player asked for it”:

1.  **Broadcast** — announcements, command descriptions (they render in every
    member's `/` picker), catalog and collection embeds, footer tips, capture
    messages. Nobody opted in; the reader is spending no attention.
2.  **Reference** — `docs/USER_GUIDE.md` and the other project docs. Read
    deliberately; exact numbers are fine.
3.  **Opt-in** — item cards (`/inventory info`), which are possession-gated: you
    can only inspect what you own. The player asked, so answer fully.
4.  **Commitment** — confirmation dialogs. The last moment before something
    irreversible; state the consequences plainly.
5.  **Internal** — docstrings, tests, admin and owner commands, this doc. No
    restrictions.


Rules
-----

 -  **R1 — Kind is always concrete.** Withholding *what* an effect does is not
    mystery, it is an unusable item.
 -  **R2 — Rate is ordinal in broadcast, exact in opt-in.** A deterministic
    effect needs no rate to be trusted; a chance effect can be invisible
    forever, so the player needs enough to tell “rare” from “broken”.
 -  **R3 — Magnitude is silent in broadcast, exact in opt-in and commitment.** A
    magnitude that does not change a decision has exactly one effect: it creates
    a comparison.
 -  **R4 — Conditions are concrete at the commitment point.** If an action can
    fail, the player is owed that fact before pressing the button.
 -  **R5 — Never publish a tunable knob in broadcast.** Spawn weights, thaw
    odds and rarity tiers are all knobs, and all of them are comparisons
    waiting to happen.
 -  **R6 — Qualitative text may be less specific than the source, never
    differently specific.** “A good payout” is fine while the number is
    unstated; it is a bug if another item pays more.
 -  **R7 — Derive opt-in prose from its oracle.** Display and effect read the
    same value so they cannot drift: `_consumption_fields` reads the item's own
    status classes (the same ones the consume glue applies), `_thaw_field` reads
    `thaw.THAW_CHANCE`, `ReactionStatus.describe` reads its own class fields,
    and the thaw confirmation reads the same knob the thaw service rolls.
 -  **R8 — No totals or denominators that reveal a hidden set's size.** “3 of 5
    frogs discovered” is a spoiler wearing a progress bar.
 -  **R9 — Do not editorialize a probability in a gain frame.** “A low chance”
    reads as “ignore this”; describe the experience (“now and then”).
 -  **R10 — Admin and owner surfaces are exempt.** Staff need the real numbers
    for asset checks and debugging; that is not a broadcast.


Anti-patterns
-------------

 -  Rarity tiers in a broadcast — a rarity tier is a tier list.
 -  “Grants 20 exp” in an announcement.
 -  “The biggest payout”, “the best odds” — dominant valuation.
 -  Odds in a command description (the picker is a broadcast surface).
 -  “A low chance” (R9).
 -  “X of Y” progress on a hidden set (R8).
 -  Opt-in prose written by hand instead of read from the oracle (R7).
 -  Hinting that an effect-free consume could pay off later — the warning
    states the fact and stops.


Surface map
-----------

Every player-facing string, classified. *Broadcast* is read without asking;
*opt-in* is the invoker's own request (their card, their standing); *commitment*
is the last screen before something irreversible; *reference* is read
deliberately; *internal* is staff tooling and code.

| Location                                                      | Surface    | Allowed to say                                                                         |
| ------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------- |
| `plugins/*/extension.py` slash command descriptions           | broadcast  | kind + ordinal rate (the `/` picker)                                                   |
| `plugins/*/extension.py` slash option descriptions            | broadcast  | kind + ordinal rate                                                                    |
| `lightbulb.Group(...)` group descriptions                     | broadcast  | kind only                                                                              |
| `plugins/*/__init__.py` `tip_sets` (footer tips)              | broadcast  | command guidance only                                                                  |
| `plugins/frogs/behaviors.py` capture announcement             | broadcast  | the catcher's own counts (their progress)                                              |
| `plugins/frogs/behaviors.py` cluster burst announcement       | broadcast  | the burst size (an outcome, not a spawn knob)                                          |
| `plugins/frogs/extension.py` `/frog catalog` collection book  | broadcast  | discovered species only, no totals (R8)                                                |
| `docs/announcements/*.md` announcement drafts                 | broadcast  | kind + ordinal rate, no tiers, no valuations                                           |
| `docs/USER_GUIDE.md`, `docs/FROG.md`, this doc                | reference  | exact numbers                                                                          |
| `plugins/frogs/items.py` `_consumption_fields`, `_thaw_field` | opt-in     | exact — item card, possession-gated                                                    |
| `plugins/frogs/statuses.py` `ReactionStatus.describe`         | opt-in     | exact — item card                                                                      |
| `/inventory view`, `/inventory info`                          | opt-in     | exact — the invoker's own holdings                                                     |
| `/experience view`, `/frog view`, the leaderboards            | opt-in     | exact — the invoker's own standing                                                     |
| `/inventory consume` confirmation embed                       | commitment | exact — effects and status; a plain grants-nothing warning when the item has no effect |
| `/inventory thaw` confirmation embed                          | commitment | exact — odds; the failure payout is named, not valued                                  |
| `plugins/frogs/species.py` `rarity`                           | internal   | nothing — never rendered anywhere                                                      |
| `/frog_catalog`, `/dev`, `/calc`, `/frog register`, modlog    | internal   | exact (R10 — staff surfaces are exempt)                                                |
| `templates.*` message JSON (level-up, rank-up, welcome)       | broadcast  | owner-authored; the owner owns that text                                               |

Fixed by this pass: the `/inventory thaw` command description carried the odds
(it renders in every member's picker — a broadcast surface); the announcement
draft enumerated the species with per-species valuations. Both are clean now.


Enforcement
-----------

Policy that lives only in prose decays, so it is checked mechanically:
`tests/core/test_information_strategy.py` fails when a broadcast surface
string carries a banned pattern — a percent sign, a digit next to “exp”, a
rarity word, or “weight”. It sweeps three surfaces:

 -  the member-facing `/` picker: command descriptions, option descriptions
    and the description of the group holding them (`USER_FACING` in
    `tests/core/test_command_guards.py` decides which commands those are, so
    the two sweeps cannot drift)
 -  the footer tips plugins declare (`Plugin.tip_sets`)
 -  the announcement drafts under `docs/announcements/`

Deliberately outside the sweep, because exactness is the point there: opt-in
item cards, the commitment dialogs and staff surfaces (R10). `_banned` is
unit-tested against deliberately banned fixtures, so the guard cannot pass by
collecting nothing. This mirrors `tests/core/test_csr_boundary.py`, which
enforces an architectural rule the same way.


Open questions
--------------

 -  **Resolved** — the collection book renders undiscovered species as nameless
    silhouettes. No count is printed (R8 holds literally), but the species count
    is visually inferable from the number of slots. Accepted trade-off: it
    advertises that there is more to find without naming any of it. A species
    can opt out of taking a slot entirely (`Species.hidden`), which is how a
    genuinely secret frog stays secret.
 -  Whether `Species.rarity` should be removed outright — it is unused by every
    player surface, and its labels contradict the weights (Pog and Classy share
    a weight; Cluster is the second most common spawn but is labeled “special”).
 -  Whether the item card keeps exact numbers. Current answer: yes — it is
    possession-gated and deliberately opt-in.
