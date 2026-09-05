"""Inventory plugin extension — /inventory view, consume, and info.

``view`` renders the shared ledger as a numbered inline-emoji grid, resolving
each stack's icon through the item-definitions registry (``bot.items``) —
an item with an ``icon_asset`` uses its published custom-emoji reference
(``bot.assets.get``), falling back to the static ``icon`` while unpublished.
Stacks whose id no longer resolves (a provider removing/renaming an item)
are hidden AND compacted away: slots are re-derived over the *visible*
stacks only (see :func:`_indexed_resolved`), so the grid never shows a gap
like "1, 2, 4". ``consume <slot>`` resolves a stack by its derived slot
number, then runs the item's own consume handler and decrements the stack.
``info <slot>`` shows the invoker's item in that slot as a description card —
thumbnail from the item's asset, title the item name, the description prose,
then one labeled embed field per item ``field``.
"""

import asyncio
from typing import Any, cast

import hikari
import lightbulb

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.items import Item

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
        indexed = await _indexed_resolved(bot, target.id)
        embed = await _build_grid(bot, indexed, target)
        await ctx.respond(embed=embed)


@inventory.register
class Consume(
    lightbulb.SlashCommand,
    name="consume",
    description="Consume an item from your inventory for its outcome.",
):
    """Confirm, then consume a stack for the item's own outcome."""

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
        # stack decrements — a failed outcome never eats items.
        await item.consume(bot, uid, self.amount)
        await bot.inventory.remove(uid, item_id, self.amount)

        embed_post = utils.prepare_embed(
            f"Consumed **`{self.amount}` {name}**!",
            f"Resulting {name}\n**`{balance}`** -> **`{balance - self.amount}`**",
        )
        await ctx.edit_response(
            utils.INITIAL_RESPONSE_IDENTIFIER, embed=embed_post
        )


@inventory.register
class Info(
    lightbulb.SlashCommand,
    name="info",
    description="Show an item's info from one of your inventory slots.",
):
    """Render an item's description card from the invoker's own inventory.

    Discovery-by-possession: slots only exist for what the member holds, so
    the card can only describe items they actually own. The card reuses the
    slot numbering of ``/inventory view`` — thumbnail from the item's asset
    (``icon_asset`` → CDN URL when published), title the display name, the
    description prose, then one labeled embed field per item ``field``.
    """

    slot = lightbulb.integer(
        "slot", "The inventory slot to inspect", min_value=1
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Resolve the slot's item and render its info embed."""
        bot = utils.bot_from(ctx)
        uid = (ctx.member or ctx.user).id

        entry = await _slot_entry(bot, uid, self.slot)
        if entry is None:
            raise UserInputError(f"No item in slot **{self.slot}**.")
        _slot, item_id, _qty = entry

        item = bot.items.item_for(item_id)
        if not bot.items.resolved(item_id):
            raise UserInputError("That item is no longer available.")

        embed = hikari.Embed(
            title=item.display_name,
            description=item.description,
            color=_COLOR,
        )
        if item.icon_asset is not None:
            url = await bot.assets.thumbnail_for(item.icon_asset)
            if url is not None:
                embed.set_thumbnail(url)
        for label, text in item.fields:
            embed.add_field(name=label, value=text)
        await ctx.respond(embed=embed)


loader.command(inventory)


# -- helpers ---------------------------------------------------------------


async def _build_grid(
    bot: CazzuBot,
    visible: list[tuple[int, str, int]],
    target: hikari.PartialUser,
) -> hikari.Embed:
    """The inventory embed: numbered inline-emoji grid of visible stacks.

    ``visible`` is the caller's compacted slot list (see
    :func:`_indexed_resolved` — every id resolves, slots are contiguous).
    Each stack resolves its icon through ``bot.items.item_for``; an item
    whose ``icon_asset`` points at an EMOJI-kind asset uses the published
    ``<:name:id>`` reference (falling back to the static ``icon`` while
    the asset is unpublished).
    """
    embed = hikari.Embed(color=_COLOR)
    embed.set_author(name=f"{target.display_name}'s Inventory")
    if not visible:
        embed.description = "Your inventory is empty."
        return embed

    current: str | None = None
    for slot, item_id, qty in visible:
        prefix = item_id.split(":", 1)[0]
        if prefix != current:
            embed.add_field(name="", value=f"**{prefix.upper()}**")
            current = prefix
        item = bot.items.item_for(item_id)
        embed.add_field(
            name=str(slot),
            value=f"{await _grid_icon(bot, item)} ×{qty}",
            inline=True,
        )
    return embed


async def _grid_icon(bot: CazzuBot, item: Item) -> str:
    """The icon glyph for one item: custom-emoji asset when published.

    An ``icon_asset`` (EMOJI-kind) resolves through ``bot.assets.get`` to
    its published ``<:name:id>``; ``None`` (unpublished: no asset guild
    configured or a pending re-sync) falls back to the static ``icon``.
    Items without an ``icon_asset`` always use ``icon``.
    """
    if item.icon_asset is not None:
        return (await bot.assets.get(item.icon_asset)) or item.icon
    return item.icon


async def _indexed_resolved(
    bot: CazzuBot, uid: int
) -> list[tuple[int, str, int]]:
    """A member's *visible* stacks as contiguous 1-based slots.

    Slots are derived, not stored: the ledger numbers every non-empty stack
    in ``ORDER BY item`` order (``bot.inventory.rows``), and the grid hides
    stacks whose id no longer resolves — a provider removing/renaming an
    item degrades the holding to hidden, non-consumable
    (``bot.items.resolved``). Filtering those out *before* numbering keeps
    the visible slots at 1, 2, 3, … with no gaps (an unresolved stack can
    never leave a hole like "1, 2, 4"). ``view``, ``info`` and ``consume``
    all resolve through this one order, so a rendered slot always addresses
    the same item everywhere.
    """
    return [
        (slot, item_id, qty)
        for slot, (item_id, qty) in enumerate(
            (
                row
                for row in await bot.inventory.rows(uid)
                if bot.items.resolved(row[0])
            ),
            start=1,
        )
    ]


async def _slot_entry(
    bot: CazzuBot, uid: int, slot: int
) -> tuple[int, str, int] | None:
    """The visible ``(slot, item_id, qty)`` row for ``slot``, or None.

    Uses the same compacted numbering as the grid (:func:`_indexed_resolved`),
    so a slot that renders always resolves to the same item here — hidden
    (unresolved) stacks are unreachable instead of addressable-but-empty.
    """
    indexed = await _indexed_resolved(bot, uid)
    return next((row for row in indexed if row[0] == slot), None)


async def _slot_balance(bot: CazzuBot, uid: int, slot: int) -> int:
    """Re-read a slot's stack at consume time (slots are derived, not stored)."""
    entry = await _slot_entry(bot, uid, slot)
    return entry[2] if entry is not None else 0
