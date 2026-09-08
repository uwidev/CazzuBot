@🔔 | Subscribed CazzuBot quickstart — new commands, inventory, and frogs

Hi friends.

If you've been here since the prefix days, this is your catch-up. `c!exp`, `c!frogs`, `c!top` — all of it is slash commands now. Type `/` in the message box and Discord lists every command the bot has.

🐸 **Frogs are items now.** No more frog counter. Every catch lands in your inventory as an actual item you can hold, inspect and use:

• `/inventory view [user]` — your inventory as a numbered grid of slots. The numbers are worked out from what you're actually holding, so a slot always points at the same item in every command. Big inventories page through with buttons, and only the person who ran the command can click them. Pass a user to peek at theirs.
• `/inventory info <slot>` — the card for the item in that slot: its art, its description, and a field spelling out exactly what consuming it does. You can only inspect what you own.
• `/inventory consume <slot> [amount]` — use one or more of a stack. The bot asks you to confirm first, and the item's effect runs before anything is deducted, so a failed outcome never eats your items.
• `/inventory thaw <slot> [amount]` — for frozen frogs only, see the season section below.

⚠️ **The old consume behaviour is gone.** `c!frogs consume` used to buy you a temporary exp multiplier. That system is retired. Consuming a frog now grants a perk of its own — no exp. The perk is spelled out on the item's own `/inventory info` card, for when you want to look it up.

📋 **Old habits → new commands**

• `c!exp` → `/experience view [user] [mode]` — your membership card
• `c!frogs` → `/frog view [member] [mode]` — your capture permit
• `c!top` → `/experience leaderboard [year] [season] [page]` — the board, paged with buttons
• `c!frogs consume N` → `/inventory consume <slot> [amount]`
• New: `/frog catalog` — your own collection book (below)

📈 **Exp, quickly.** Chatting is the only thing that grants exp — no item does — with a cooldown between awarded messages. Your first messages of the day count for more, and the value tapers off the more you talk, resetting each day. Exp comes in seasons — quarters — and seasonal totals reset when a season turns over while lifetime totals never do. `/experience view` shows your rank role, level, exp, your percentile, and where you sit on the board; the `mode` option switches between seasonal and lifetime. Rank roles are handed out automatically as you cross level thresholds. `/experience leaderboard` pages through the board, and its buttons can jump whole seasons at a time.

🎣 **Catching, in practice.** Frogs spawn in whichever channels are set up for it, on a deliberately unpredictable schedule, and they only hang around for a short while. The first click wins: catching pings you with the frog's emoji and your new totals, and the message disappears either way — caught or bored.

✨ **The other frogs are finally awake.** Until now only Basic Frogs could spawn. The rest were built and then left switched off. They're on now, and they don't all behave the same: some are just a catch, some may have the bot react to your messages for a while, one hands you a role, and one refuses to be caught at all — see below. Which one you meet is up to chance, so there's no wrong frog to want.

Use a second one while its perk is still running and it lasts longer rather than getting stronger.

📖 **Your collection book.** `/frog catalog` isn't a list of everything any more — it's yours. It fills in as you meet frogs, showing each one you've found with its art and description, and it says nothing about the ones you haven't. No names, no previews, no spoilers. Go and find them.

💥 **The one that doesn't get caught.** Click Catch on her and she bursts instead, flinging a handful of Basic Frogs into the channels around her — same category only, so she won't leak into unrelated channels. Most bursts are small; now and then a big one lands. Those frogs are real, catchable, and vanish like any other spawn, so stick around after the bang.

📜 **Your frog permit.** `/frog view` shows how many frogs you've caught, where you rank, your percentile, and a snippet of the frogs you're currently holding. It comes in seasonal and lifetime flavours, same as the exp card.

❄️ **Season end freezes everything.** On the 1st of January, April, July and October, at midnight UTC, every frog in the server freezes where it sits. You keep the species you caught — what you lose is the value. Frozen frogs are trophies: they cannot be consumed.

`/inventory thaw <slot> [amount]` is the only way back, and it's a gamble per frog. A win hands the normal frog back, perk and all, ready to use — and it freezes again next season if you sit on it. A loss leaves you with 💀 Frog Remains instead. The odds are on the frog's own card, if you want to look before you leap.

So the pattern is simple: use what you want before the rollover, or gamble on the thaw after.

💡 **Stuck?** Every frog and inventory embed carries a rotating footer tip with the exact command you're looking for.

🐸 Go catch some frogs.
