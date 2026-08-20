"""Inventory plugin extension — /inventory view and /inventory consume.

``view`` renders the shared ledger as a numbered inline-emoji grid, resolving
each stack's icon through the item-definitions registry (``bot.items``);
unresolved ids (a provider that was unregistered/removed) are hidden rather
than shown as garbage. ``consume <slot>`` resolves a stack by its derived slot
number, then runs the item's own consume handler and decrements the stack.
"""

import asyncio
from typing import Any, cast

import hikari
import lightbulb

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError

loader = lightbulb.Loader()

_COLOR = hikari.Color.from_hex_code("#a2dcf7")

inventory = lightbulb.Group(
    "inventory", "View and consume your inventory."
)


@inventory.register
class View(
    lightbulb.SlashCommand,
    name="view",
    description="Show a member's numbered inventory grid.",
):
    """Render a member's full inventory in a numbered inline-emoji grid."""

    user = lightbulb.user("user", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the inventory grid embed."""
        bot = utils.bot_from(ctx)
        target = self.user or ctx.member or ctx.user
        indexed = await bot.inventory.rows_indexed(target.id)
        embed = _build_grid(bot, indexed, target)
        await ctx.respond(embed=embed)


@inventory.register
class Consume(
    lightbulb.SlashCommand,
    name="consume",
    description="Consume an item from your inventory for its effect.",
):
    """Confirm, then consume a stack for the item's own effect."""

    slot = lightbulb.integer(
        "slot", "The inventory slot to consume", min_value=1
    )
    amount = lightbulb.integer(
        "amount", "How many to consume", default=1, min_value=1
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Resolve the slot, confirm, run the item consume, decrement."""
        bot = utils.bot_from(ctx)
        uid = (ctx.member or ctx.user).id

        entry = await _slot_entry(bot, uid, self.slot)
        if entry is None:
            raise UserInputError(f"No item in slot **{self.slot}**.")
        _slot, item_id, balance = entry

        item = bot.items.item_for(item_id)
        if not bot.items.resolved(item_id):
            raise UserInputError("That item is no longer available.")
        if item.consume is None or not bot.items.consumable(item_id):
            raise UserInputError(
                f"**{item.display_name or 'That item'}** cannot be consumed."
            )
        if balance < self.amount:
            raise UserInputError(
                f"You only have **{balance}** of that item to consume."
            )

        name = item.display_name or item_id
        desc = (
            f"You are about to consume **`{self.amount}` {name}**.\n\n"
            f"Resulting {name}\n**`{balance}`** -> "
            f"**`{balance - self.amount}`**\n\n"
            "Please confirm."
        )
        embed = utils.prepare_embed("**Confirmation**", desc)
        menu = utils.ConfirmMenu(uid, delete_after=False)
        await ctx.respond(embed=embed, components=cast(Any, menu))
        try:
            await menu.attach(ctx.client, timeout=120)
        except asyncio.TimeoutError:
            await ctx.delete_response(utils.INITIAL_RESPONSE_IDENTIFIER)
            return
        if not menu.value:
            await ctx.delete_response(utils.INITIAL_RESPONSE_IDENTIFIER)
            return

        # re-check the balance at the very moment of consumption
        bal_now = await _slot_balance(bot, uid, self.slot)
        if bal_now < self.amount:
            raise UserInputError("Not enough of that item to consume.")

        # the item's own consume runs first (grants exp etc.), then the
        # stack decrements — a failed effect never eats items.
        await item.consume(bot, uid, self.amount)
        await bot.inventory.remove(uid, item_id, self.amount)

        embed_post = utils.prepare_embed(
            f"Consumed **`{self.amount}` {name}**!",
            f"Resulting {name}\n**`{balance}`** -> **`{balance - self.amount}`**",
        )
        await ctx.edit_response(
            utils.INITIAL_RESPONSE_IDENTIFIER, embed=embed_post
        )


loader.command(inventory)


# -- helpers ---------------------------------------------------------------


def _build_grid(
    bot: CazzuBot,
    indexed: list[tuple[int, str, int]],
    target: hikari.PartialUser,
) -> hikari.Embed:
    """The inventory embed: numbered inline-emoji grid across namespaces.

    Each non-empty stack resolves its icon through ``bot.items.item_for``;
    stacks whose id no longer resolves (a provider that was removed from the
    registry) are hidden instead of shown as raw keys.
    """
    embed = hikari.Embed(color=_COLOR)
    embed.set_author(name=f"{target.display_name}'s Inventory")
    visible = [row for row in indexed if bot.items.resolved(row[1])]
    if not visible:
        embed.description = "Your inventory is empty."
        return embed

    current: str | None = None
    for slot, item_id, qty in visible:
        prefix = item_id.split(":", 1)[0]
        if prefix != current:
            embed.add_field(name="", value=f"**{prefix.upper()}**")
            current = prefix
        icon = bot.items.item_for(item_id).icon
        embed.add_field(
            name=str(slot), value=f"{icon} ×{qty}", inline=True
        )
    return embed


async def _slot_entry(
    bot: CazzuBot, uid: int, slot: int
) -> tuple[int, str, int] | None:
    """The ``(slot, item_id, qty)`` row for ``slot``, or None."""
    indexed = await bot.inventory.rows_indexed(uid)
    return next((row for row in indexed if row[0] == slot), None)


async def _slot_balance(bot: CazzuBot, uid: int, slot: int) -> int:
    """Re-read a slot's stack at consume time (slots are derived, not stored)."""
    entry = await _slot_entry(bot, uid, slot)
    return entry[2] if entry is not None else 0
