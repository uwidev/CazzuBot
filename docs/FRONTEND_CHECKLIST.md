Frontend Behavior QA Checklist
==============================

Content + formatting test pass for the user-facing (Discord-rendered) surface:
slash commands, embeds, messages, buttons, modals, templates.

One checkbox per rendered surface. Each item is two lines: an actionable
one-line check, then the supporting context that says what to look for. Run it
live in the dev guild, inspect the output, and judge: **is the content present,
and is the embed shape (author, title, thumbnail, fields, footer, color, code
blocks) complete and sufficient — nothing missing, nothing overstuffed?**

Numeric/statistical correctness (exp values, chances, durations, percentile
math, page math) is covered by tests and code — do not re-verify those numbers
by hand here. The checklist covers what only a live render can show.


Running it
----------

 -  Dev mode only (`uv run python main.py -d`) — never mutate the production
    guild.
 -  Use an owner account for `[Owner]` commands, an admin/integration-role
    account for `[Admin]`, and a plain member account for member paths.
 -  Non-authorized users must be refused without leaking command behavior.
 -  As a second pair of eyes, compare rendered copy against
    `docs/USER_GUIDE.md` (member commands) — flag drifts, but don't rewrite
    docs in this pass.

   - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


Priority 1 — Frogs & inventory
------------------------------

 -  [x] Render `/frog view` and eyeball the capture-permit embed.
    Content: total captures, per-species inventory lines
    (`name (normal|frozen): qty`, “No frogs yet.” state), percentile line,
    `py` scoreboard with the `@` row marker; shape: author + icon, avatar
    thumbnail, layout order and blank lines. Also run the empty-server and
    not-on-board plain-text replies.

    The Inventory section is outdated, from the days before Inventory
    was implemented. It needs to be reshaped.

    This command should only show a snippet of the user's current inventory,
    filtered to show only normal frogs. In other words, the frogs that are
    active for this current season. It should use a format similar to how
    inventory works right now, minus the inventory slot row. Sort by quantity in
    ascending order. Make sure to filter and show only frog-type objects (future
    may have non-frog items).

    Remove the Author field.

    Here is a json field of a rough example/template to work with.

    ~~~~ json
    {
      "content": "",
      "tts": false,
      "embeds": [
        {
          "id": 652627557,
          "title": "Usara's Frog Capture Permit",
          "description": "Total frogs captured: **`53`**\n\n**__Inventory__**\nC x34\nA x10\nB x3\n\nYou are currently the `XXth` percentile of all members.\n```\nleaderboard here\n```",
          "color": 2326507,
          "fields": [],
          "thumbnail": {
            "url": "https://images-ext-1.discordapp.net/external/5vJssjBMlgoA9bL5JIJBXNNX1OD6tkS1pnBZw_6b65c/%3Fsize%3D4096/https/cdn.discordapp.com/avatars/92664421553307648/07ffd60432871c58f2a01189edc3a6bd.png?format=webp&quality=lossless"
          }
        }
      ],
      "components": [],
      "actions": {},
      "flags": 0,
      "username": "Cazzubot-Dev",
      "avatar_url": "https://cdn.discordapp.com/avatars/1424584066295922710/d058ff5a2383ae511bc9bbb60d81dac5.webp?size=2048"
    }
    ~~~~

    Also, there should be a footer. This footer text cycles randomly on a set
    of strings. This set are tips relating to frogs. One of these tips should be
    about how to check what a frog does. Another should be about how to consume
    frogs. More tips are welcome. This should be generic, some "get_tip()" call
    that others can pull from.

 -  [x] Open `/frog catalog` and inspect the species list embed.
    One field per species with its art emoji (or description-only fallback)
    plus the description; nothing beyond name/art/description; Cluster Frog
    present with no consumable-exp claim.

    Bold the frog names.

    Also put footer tips here.

 -  [x] Trigger a spawn and inspect the frog message + Catch button.
    Content is the species' art emoji, else plain name — never “None”;
    single green button with net emoji; deletes itself when bored; click
    acked invisibly, message removed on capture.

    All captures should ping and mention the person who caught the frog. I don't
    think pings work when they're in an embed. Ping on the message content.

    Should also show the emoji of the frog on the message content.

    Should also state the new count for the that frog item, if received.

    Cluster frogs are never actually "caught". Instead, it should state that the
    catch failed, but as a result it bursted... blah blah blah.

    Remove the thumbnail.

 -  [x] Catch a frog and inspect the capture announcement.
    Both variants: the built-in embed (totals, species identity, art
    thumbnail when published) and a `/frog set message <json>` template
    (placeholders substituted, no leftover `{...}`, embeds/fields/color as
    configured).

    Fine. We will actually plan to move this hardcoded. There is not much need
    for this to be dynamically configured at runtime. A set and forget, and if
    need changed, it's developer changes it.

 -  [x] Force-spawn with `/frog spawn` and `/frog fake`; inspect the replies.
    Frog message becomes the slash response (content + catch button, no
    extra confirmation); bad species value refused cleanly; same shape as
    the scheduled spawn.

    Remove frog fake. I think I had this here to mess around with people to
    spawn fake frogs that don't reward anything. Delete old code.

 -  [x] Catch a Cluster Frog and inspect the burst announcement.
    Announcement embed: who caught it, what happened, art thumbnail when
    published (art-less otherwise); child frogs spawn with their own Catch
    buttons and get cleaned up.

    See earlier comment on frog spawns.

 -  [x] Render `/inventory view` and inspect the grid embed.
    Author, inline slot fields (`icon ×qty`), group headers per item type,
    empty-inventory state, contiguous slot numbering with no “1, 2, 4”
    holes; same slot addresses the same item as info/consume/thaw.

    Do a similar framework like `/frog view`. No leaderboard.

    Set thumbnail to be the user's pfp.

    Remove the author field. Use title instead, `User's Inventory`.

    Create a set of tip strings here as well. Footer has a tip. One could be how
    to check what items do. Another is how to use an item.

    Slots should be like [1] [2] [3] rather than just a plain number. Try your
    best to center the slot number above the item and its quantity. Have better
    dividers between items. Perhaps a `|` or multiple spaces.

    Remove the "FROG" text. The inventory is one basket, not categories (for
    now).

    I'm not sure how sorting works right now, but sort from quantity descending
    order.

 -  [x] Open `/inventory info` on a few slots and inspect the item card.
    Thumbnail when the art asset is published, title = display name,
    description prose, one labeled field per declared `fields` (frozen frog
    → “On thaw”, normal → “On consumption”). Shape sufficient — not just
    the data.

    Add footer tips. I may say hints or tips. They are the same.

 -  [x] Consume an item end-to-end and inspect both embeds.
    Confirmation embed (before/after quantity block, “Please confirm.”,
    -sarono footer) → Yes/No buttons → final “Consumed!” embed with the
    quantity line. Labels, bolding/backticks on numbers, footer, no stray
    content.

    Footer icon, change to bot avatar.

    Set the thumbnail to the item url image.

    Show the item effects and the results of consuming said stacks.

    For exp, it should show before and after.

    Definitely show the resulting status, if any.

 -  [~] Thaw a frozen frog and inspect both embeds.
    Confirmation embed explaining the gamble → “Thawed!” result embed with
    the survived/remains tally line. Clear copy, consistent number
    formatting.

    Modify the development database and give me `92664421553307648` some frozen
    frogs so I can test this.

 -  [~] After a quarterly rollover, re-render the frog + inventory surfaces.
    `/frog view` lists frozen per-species rows; `/inventory view`/`info`
    render the frozen items + thaw messaging. Flag any surface still
    describing the old fold-to-basic reset.

    Write a debug owner command to do quarterly rollover on the provided user.
    Then I can inspect if this works properly.


Priority 2 — Remaining member-facing surfaces
---------------------------------------------

 -  [ ] Render `/experience view` and inspect the membership card.
    Author + icon, avatar thumbnail, rank line (rank mention or `None`),
    level + exp lines, percentile line, `py` scoreboard with `@` row
    marker; the no-experience-yet card. Layout, bolding/backticks,
    alignment.

    See comments on `/frog view`. Except there shouldn't be an inventory view
    here.

 -  [ ] Render the leaderboard and inspect the embed.
    Author, leader avatar thumbnail, year/season/page header lines, 10-row
    `py` code block with your row highlighted, empty-period text.

 -  [ ] Click through the pager and watch the re-render.
    ⬅ ◀ ▶ ➡ buttons re-render in place; page bounds respected (first/last,
    no strand); invoker-only (others get the ephemeral “not yours to page”
    reply); buttons stripped on 30s timeout.

 -  [ ] Trigger a level-up and inspect the configured message.
    `level.message` template renders with `{level_old}`/`{level_new}` +
    member tokens, deletes after 7s; quiet-channel suppression works;
    unset template = nothing, no crash.

 -  [ ] Trigger a rank-up and inspect the template message.
    Seasonal rank template renders on rank-up with rank mentions; lifetime
    rank-ups stay silent; unset template = nothing.

 -  [ ] Complete onboarding / gain the monitored role; inspect the welcome.
    Template renders with `{avatar} {name} {mention} {id}`; no double
    welcome; `/welcome demo` previews as the invoker; `/welcome raw` dumps
    JSON; default role assigned in pending mode.

 -  [ ] Exercise the baka counter lifecycle and inspect the embed.
    Create (bored thumbnail + idle footer), each press (count up, baka
    thumbnail, recent names footer), idleness reset; stale button → “not a
    baka counter anymore”.

 -  [ ] Run the fun commands and inspect each reply.
    `/ping` latency line, `/noot`, `/echo` round-trip, `/hashiresoriyo`,
    `/info [member]` join-date/role-count line and the not-in-server reply.

 -  [ ] Run `/misc banner|welcome|week` and inspect the window replies.
    Each outcome: success, bad link, no image, permission denial, no
    welcome screen, week/ISO-week lines. Correct `✓`-prefixed ephemeral
    messages, sensible copy.

 -  [ ] Send a poll and inspect the poll embed.
    Title/description, -sarono footer, “Poll ID#{pid}” footer with
    open/closed icon, Vote button; 0-items and unknown-id refusals.

 -  [ ] Vote through the modal and inspect each reply.
    Modal title/label/placeholder copy; valid vote → recorded reply;
    invalid vote error lines; closed-poll refusal.

 -  [ ] Open, close, and stat a poll; inspect each result.
    Close removes the Vote button and appends results, open restores it and
    strips them; stats code block (Item/Count/Percent) reads clearly.

 -  [ ] Run `/board scrape` and `/board post`; inspect the window flows.
    Scrape progress + skipped/duplicate lines; post stitch/truncation/
    prune/dead-row warnings and final grid (content links above the
    attachment, sized grid image).

 -  [ ] Run the weekly board flow and inspect the combined message.
    Announcement (role ping + week header, grid attachment, poll embed +
    Vote button) and the winner/no-votes close-out messages.


Priority 3 — Shared surfaces & cross-cutting
--------------------------------------------

 -  [ ] Trigger a few windowed commands and check the prefix glyphs.
    `✓` / `⚠︎` / `✖` render as intended (not boxes or emoji) across every
    windowed command.
 -  [ ] Trigger a few invalid inputs and inspect the error replies.
    Any `UserInputError` surfaces as a clean ephemeral message (no
    traceback); option-conversion failures read human-friendly; mod-gate
    refusals are silent.
 -  [ ] Set templates with every placeholder and check substitution.
    Across level-up, rank-up, frog capture, and welcome: every placeholder
    substitutes in content, embeds, author, footer, and field strings
    (deep\_map); none leak raw.
 -  [ ] Put a mention in a template and verify the ping behavior.
    Template messages ping exactly the users/roles written as `<@id>`/
    `<@&id>`; `allowed_mentions: true` permits @everyone/@here only when
    present; `false` pings nothing.
 -  [ ] Scan every emoji-rendering surface for fallback behavior.
    Published assets show the `<:name:id>` tag; unpublished assets fall
    back to static icons/plain names; the literal text “None” must never
    appear.
 -  [ ] Cycle view → info → consume → thaw on a mixed inventory.
    Normal + frozen + remains stacks: slot numbering stays contiguous and
    stable across commands after each mutation.
 -  [ ] Check ephemerality and cleanup timing across flows.
    Windows/errors/confirm-timeouts are ephemeral, member cards public;
    pager buttons strip on timeout, confirm prompts delete or strip on
    answer, level-up/rank-up messages delete after their delay.
 -  [ ] Push a long inventory grid and a long leaderboard page.
    Oversized embeds truncate or degrade gracefully (never a 400).
