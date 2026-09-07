"""Inventory plugin extension — /inventory view, consume, and info.

``view`` renders the shared ledger as an **inline-field grid**, paged
through with a ◀/▶ button pager (:class:`InventoryPager`, mirroring the
/experience leaderboard's TopMenu): each visible slot renders as one
embed field in inline layout (Discord wraps 3 per row), the field name
the backticked bracket slot token (``[ 1 ]``) and the value the item's
**emoji** followed by ``×<qty>`` (an item with an ``icon_asset`` uses its
published custom-emoji reference — ``bot.assets.get`` — falling back to
the static ``icon`` while unpublished); the title names the member
(``X's Inventory``, no author field), the thumbnail is the member's
profile picture, and the footer cycles one random item tip. Discord caps
an embed at 25 fields, so the grid pages at that boundary. Stacks whose
id no longer resolves (a provider removing/renaming an item) are hidden
AND compacted away: slots are re-derived over the *visible* stacks only
(see :func:`_indexed_resolved`), ranked frozen-frog-trophies-last then
by quantity descending (largest stacks first), so the grid never shows a
gap like "1, 2, 4".
``consume <slot>`` resolves
a stack by its derived slot number, then runs the item's own consume
handler and decrements the stack; for exp-granting items its final
embed also shows the seasonal exp before/after the consume, and when
the consume grants a status the **resulting** status (the granted
status class's human prose) appears as a field of its own — nothing
when the item grants no status.
``info <slot>`` shows the invoker's item
in that slot as a description card — thumbnail from the item's asset,
title the item name, the description prose, then one labeled embed field
per item ``field``.
"""

import asyncio
from typing import Any, cast

import hikari
import lightbulb
import pendulum

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.items import Item
from cazzubot.statuses import Scope
from cazzubot.tips import get_tip

from plugins.misc.asset import random_footer_icon

loader = lightbulb.Loader()

_COLOR = hikari.Color.from_hex_code("#a2dcf7")

# Discord caps an embed at 25 fields — the grid pages at that boundary.
PAGE_SIZE = 25

inventory = lightbulb.Group(
    "inventory", "View and consume your inventory."
)


@inventory.register
class View(
    lightbulb.SlashCommand,
    name="view",
    description="Show a member's numbered inventory slots.",
):
    """Render a member's full inventory as a paged inline-field grid.

    The pager (:class:`InventoryPager`) is attached always — a single
    page clamps both buttons, and 26+ slots page at 25 fields per page —
    and its buttons are stripped when the 30s attach window lapses.
    """

    user = lightbulb.user("user", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the inventory grid embed and attach the pager."""
        bot = utils.bot_from(ctx)
        target = self.user or ctx.member or ctx.user
        indexed = await _indexed_resolved(bot, target.id)
        page = 1
        embed = await _build_grid(bot, indexed, target, page=page)
        menu = InventoryPager(bot, ctx, indexed, target, page=page)
        # the menu is a sequence of row builders (no public build())
        await ctx.respond(embed=embed, components=cast(Any, menu))
        try:
            await menu.attach(ctx.client, timeout=30)
        except asyncio.TimeoutError:
            # the pager's attach window lapsed — strip the buttons
            await ctx.edit_response(
                utils.INITIAL_RESPONSE_IDENTIFIER, component=None
            )


@inventory.register
class Consume(
    lightbulb.SlashCommand,
    name="consume",
    description="Consume an item from your inventory for its outcome.",
):
    """Confirm, then consume a stack for the item's own outcome.

    Both the confirmation and the final "Consumed!" embeds carry the bot
    avatar footer and the item's published art as thumbnail when available
    (unpublished → no thumbnail). See :func:`_apply_item_thumbnail`. The
    final "Consumed!" embed adds an effects section — the item's
    description prose plus one labeled field per item ``field`` (the "On
    consumption" blurb for frogs: what consuming does) — then, for
    exp-granting items, the seasonal exp before/after the consume (only
    when the consume actually changed it), then — when the consume
    granted a status — the **resulting** status (the granted status
    class's human text, read back from the live contribution; absent
    when the item grants none), and finally the stack-consumption
    result line (the resulting quantity).
    """

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
        # frozen frogs are trophies — refuse before the confirm (the item's
        # own consume glue raises too; this keeps the refusal one step up)
        from plugins.frogs.thaw import frozen_species_of

        if frozen_species_of(item_id) is not None:
            raise UserInputError(
                "Frozen frogs cannot be consumed — thaw them first."
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
        embed = utils.prepare_embed(
            "**Confirmation**", desc, footer_icon=utils.BOT_AVATAR_URL
        )
        await _apply_item_thumbnail(embed, bot, item)
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
        # stack decrements — a failed outcome never eats items. Capture
        # the exp before/after so exp-granting items can report the gain.
        exp_before = await _seasonal_exp(bot, uid)
        await item.consume(bot, uid, self.amount)
        exp_after = await _seasonal_exp(bot, uid)
        await bot.inventory.remove(uid, item_id, self.amount)

        # the final "Consumed!" embed: the description carries the item's
        # prose, then one labeled field per item field (the "On consumption"
        # blurb for frogs — what consuming does), then — only when the
        # consume granted exp — the seasonal exp before/after, then —
        # when the consume granted a status — the resulting status, then
        # the stack-consumption result (what consuming them did: the
        # resulting quantity).
        embed_post = utils.prepare_embed(
            f"Consumed **`{self.amount}` {name}**!",
            item.description,
            footer_icon=utils.BOT_AVATAR_URL,
        )
        for label, text in item.fields:
            embed_post.add_field(name=label, value=text)
        if exp_after != exp_before:
            embed_post.add_field(
                name="Seasonal Exp",
                value=f"**`{exp_before}`** -> **`{exp_after}`**",
            )
        # the resulting status, if any — the ground truth is the status
        # contribution this consume just published (provenance = item_id);
        # the class's describe() is the human text. The item declares its
        # statuses exactly as its consume glue applies them; confirm each
        # is actually live for this member before showing it, and items
        # that grant no status (basic, remains) render nothing.
        from plugins.frogs.items import item_statuses

        resulting: list[str] = []
        for status in item_statuses(item_id):
            contribution = await bot.statuses.fetch(
                Scope.member(uid), status.seam, status.key
            )
            if (
                contribution is not None
                and contribution.payload.get("from") == item_id
            ):
                resulting.append(status.describe())
        if resulting:
            embed_post.add_field(name="Status", value="\n".join(resulting))
        embed_post.add_field(
            name=f"Resulting {name}",
            value=f"**`{balance}`** -> **`{balance - self.amount}`**",
        )
        await _apply_item_thumbnail(embed_post, bot, item)
        await ctx.edit_response(
            utils.INITIAL_RESPONSE_IDENTIFIER, embed=embed_post
        )


@inventory.register
class Thaw(
    lightbulb.SlashCommand,
    name="thaw",
    description="Thaw a frozen frog: 50% survives, 50% becomes Frog Remains.",
):
    """Thaw a frozen frog with a 50/50 gamble (slot addressing like consume).

    Same shape as ``consume``: resolve a slot, confirm the gamble, re-check
    the balance, then roll each unit through the frogs thaw service. The
    tally ("x survived, y became Frog Remains") is edited into the prompt.
    """

    slot = lightbulb.integer(
        "slot", "The inventory slot to thaw", min_value=1
    )
    amount = lightbulb.integer(
        "amount", "How many to thaw", default=1, min_value=1
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Resolve the slot, confirm the gamble, roll, and report the tally."""
        # deferred: the thaw service imports the frogs package — loaded
        # lazily so the inventory extension never hard-couples to it
        from plugins.frogs.thaw import frozen_species_of, thaw_frogs

        bot = utils.bot_from(ctx)
        uid = (ctx.member or ctx.user).id

        entry = await _slot_entry(bot, uid, self.slot)
        if entry is None:
            raise UserInputError(f"No item in slot **{self.slot}**.")
        _slot, item_id, balance = entry

        item = bot.items.item_for(item_id)
        if not bot.items.resolved(item_id):
            raise UserInputError("That item is no longer available.")
        species_key = frozen_species_of(item_id)
        if species_key is None:
            raise UserInputError(
                f"**{item.display_name or 'That item'}** is not a frozen "
                "frog — only frozen frogs can be thawed."
            )
        if balance < self.amount:
            raise UserInputError(
                f"You only have **{balance}** frozen frog(s) in that slot."
            )

        name = item.display_name or item_id
        desc = (
            f"You are about to thaw **`{self.amount}` {name}**.\n\n"
            f"Each has a **50%** chance to survive as a {name}, and "
            "**50%** to become **Frog Remains** (3 exp).\n\n"
            f"Resulting {name}\n**`{balance}`** -> "
            f"**`{balance - self.amount}`**\n\n"
            "Please confirm."
        )
        embed = utils.prepare_embed(
            "**Confirmation**", desc, footer_icon=utils.BOT_AVATAR_URL
        )
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

        # re-check the balance at the very moment of thawing
        bal_now = await _slot_balance(bot, uid, self.slot)
        if bal_now < self.amount:
            raise UserInputError("Not enough frozen frogs to thaw.")

        outcome = await thaw_frogs(bot, uid, species_key, self.amount)
        embed_post = utils.prepare_embed(
            "Thawed!",
            f"**`{outcome.survived}`** survived as **{name}**, "
            f"**`{outcome.remains}`** became **Frog Remains**.",
            footer_icon=utils.BOT_AVATAR_URL,
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
    The footer cycles one random item tip (``get_tip("item")`` via
    ``cazzubot.tips``) — the plugin's own "item" tip_sets, the same set as
    /inventory view's footer.
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
        # the footer cycles one random item tip per render — the same set
        # as the /inventory view footer (the plugin's "item" tip_sets,
        # queried via cazzubot.tips.get_tip), with a random cirno emoji
        # from the shared misc assets as the icon
        embed.set_footer(
            text=get_tip("item"),
            icon=await random_footer_icon(bot),
        )
        await ctx.respond(embed=embed)


loader.command(inventory)


class InventoryPager(lightbulb.components.Menu):
    """Inventory grid pager: page ◀/▶ through the 25-field pages.

    Mirrors /experience leaderboard's TopMenu: the ◀/▶ buttons re-render
    the grid at the previous/next page (bounds clamped — page never drops
    below 1 nor above the last page), only the slash invoker may page
    (everyone else gets the ephemeral "This inventory is not yours to
    page." denial), and the buttons are stripped when the menu's attach
    window lapses (the :class:`View` command edits ``component=None`` on
    timeout). Attached always — a 1-page grid clamps both buttons into
    no-ops, and a >25-slot grid pages 25 fields at a time.
    """

    def __init__(
        self,
        bot: CazzuBot,
        ctx: lightbulb.Context,
        visible: list[tuple[int, str, int]],
        target: hikari.PartialUser,
        page: int = 1,
    ) -> None:
        """Remember the inventory snapshot and build the pager buttons."""
        super().__init__()
        self.bot = bot
        self.ctx = ctx
        self.visible = visible
        self.target = target
        self.author_id = (ctx.member or ctx.user).id
        self.page = page
        self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self._prev_page, emoji="◀"
        )
        self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self._next_page, emoji="▶"
        )

    @property
    def _max_page(self) -> int:
        """The last page index — every ``PAGE_SIZE`` slots boundary one."""
        return max((len(self.visible) - 1) // PAGE_SIZE + 1, 1)

    async def _edit(self, mctx: lightbulb.components.MenuContext) -> None:
        """Re-render the grid embed at the current page (atomic ack+edit)."""
        embed = await _build_grid(
            self.bot, self.visible, self.target, self.page
        )
        # respond(edit=True) is the atomic ack+edit: lightbulb menu clicks
        # arrive un-acked, and edit_response on the un-acked interaction 404s
        await mctx.respond(edit=True, embed=embed)

    async def _deny(self, mctx: lightbulb.components.MenuContext) -> None:
        """Reply that the inventory is not the clicker's to page."""
        await mctx.respond(
            "This inventory is not yours to page.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def _guard(self, mctx: lightbulb.components.MenuContext) -> bool:
        """True when the clicker may page this inventory."""
        if mctx.interaction.user.id != self.author_id:
            await self._deny(mctx)
            return False
        return True

    async def _prev_page(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        """Page backward, clamped at page 1."""
        if not await self._guard(mctx):
            return
        self.page = max(self.page - 1, 1)
        await self._edit(mctx)

    async def _next_page(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        """Page forward, clamped at the last page (no stranded tail)."""
        if not await self._guard(mctx):
            return
        self.page = min(self.page + 1, self._max_page)
        await self._edit(mctx)


# -- helpers ---------------------------------------------------------------


async def _build_grid(
    bot: CazzuBot,
    visible: list[tuple[int, str, int]],
    target: hikari.PartialUser,
    page: int = 1,
) -> hikari.Embed:
    """The inventory embed: an inline-field grid, ``PAGE_SIZE`` slots/page.

    Each visible slot renders as one embed field in inline layout
    (``inline=True`` — Discord wraps 3 per row automatically): the field
    **name** is the backticked bracket slot token (``[ 1 ]``, ``[ 2 ]``,
    …) and the **value** is the item's emoji glyph followed by
    ``×<qty>`` (e.g. ``🐸 ×50``, or the published ``<:name:id>`` custom
    emoji when the item has an ``icon_asset`` — see :func:`_grid_icon`).
    Only the current page's slots
    are added — the embed caps at 25 fields, so slot 26 starts the next
    page and paging is the caller's job via :class:`InventoryPager`.
    The title carries the target's real display name (``X's Inventory``
    — no author field), the thumbnail is the target's profile picture
    (``display_avatar_url``, set only when the partial user resolves
    one), and the footer cycles one random item tip per render
    (``get_tip("item")`` via ``cazzubot.tips`` — this plugin's own "item"
    tip_sets, the same set as /frog view and the /inventory info card, with a
    random cirno emoji from the shared misc assets as the icon). ``visible``
    is the caller's
    compacted slot list (see :func:`_indexed_resolved`) — every id
    resolves, slots are contiguous, ordered by quantity descending. The
    empty inventory keeps its prose state: the description reads "Your
    inventory is empty." with no fields and nothing to page.
    """
    embed = hikari.Embed(
        title=f"{_target_name(target)}'s Inventory", color=_COLOR
    )
    display_avatar_url = getattr(target, "display_avatar_url", None)
    if display_avatar_url is not None:
        embed.set_thumbnail(str(display_avatar_url))
    # cycle one random item tip through the footer per render — the tip
    # sets live in this plugin's own tip_sets (context "item"), shared with
    # /frog surfaces via the core, and the footer icon pulls a random cirno
    # emoji from the shared misc assets (plugins.misc.asset — the tip
    # surfaces' icon provider)
    embed.set_footer(
        text=get_tip("item"),
        icon=await random_footer_icon(bot),
    )
    if not visible:
        embed.description = "Your inventory is empty."
        return embed

    start = (page - 1) * PAGE_SIZE
    for slot, item_id, qty in visible[start : start + PAGE_SIZE]:
        item = bot.items.item_for(item_id)
        embed.add_field(
            name=f"`[ {slot} ]`",
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


def _target_name(target: hikari.PartialUser) -> str:
    """The target's display name — the real one, never the literal "User".

    ``target`` may be a partial user (a ``user`` option resolved without
    the richer Member fields), so fall back to the username and then the
    raw id when a display name is unavailable.
    """
    name = getattr(target, "display_name", None)
    if not isinstance(name, str) or not name:
        name = getattr(target, "username", None)
    return name if isinstance(name, str) and name else str(target.id)


async def _apply_item_thumbnail(
    embed: hikari.Embed, bot: CazzuBot, item: Item
) -> None:
    """Set ``embed``'s thumbnail to the item's published art, when any.

    Mirrors the /inventory info card: an ``icon_asset`` resolves through
    ``bot.assets.thumbnail_for`` to the CDN URL only while the art asset is
    published; while unpublished that returns ``None`` and the embed keeps
    no thumbnail (no ``"None"`` leak). Used by the consume embeds so both
    the confirmation and the final "Consumed!" keep the image current.
    """
    if item.icon_asset is None:
        return
    url = await bot.assets.thumbnail_for(item.icon_asset)
    if url is not None:
        embed.set_thumbnail(url)


async def _indexed_resolved(
    bot: CazzuBot, uid: int
) -> list[tuple[int, str, int]]:
    """A member's *visible* stacks as contiguous 1-based slots.

    Slots are derived, not stored. Start from the store's every-non-empty-
    stack read (``bot.inventory.rows``, ``ORDER BY item``), hide stacks
    whose id no longer resolves — a provider removing/renaming an item
    degrades the holding to hidden, non-consumable (``bot.items.resolved``)
    — then rank the *visible* stacks: **frozen-frog trophies sort last**
    (after every live item), then by **quantity, descending** (largest
    stacks first; ties keep item order — a stable sort). Filtering out the
    hidden stacks *before* numbering keeps the visible slots at 1, 2, 3, …
    with no gaps (an unresolved stack can never leave a hole like
    "1, 2, 4"). ``view``, ``info``, ``consume`` and ``thaw`` all resolve
    through this one order, so a rendered slot always addresses the same
    item everywhere — the sort lives here (not in the store) exactly so
    that every command sees the same slot numbering.
    """
    visible = [
        row
        for row in await bot.inventory.rows(uid)
        if bot.items.resolved(row[0])
    ]
    # frozen trophies last, then qty descending (largest first), ties keep
    # the store's item order (stable sort)
    visible.sort(key=lambda row: (_is_frozen(row[0]), -row[1], row[0]))
    return [
        (slot, item_id, qty)
        for slot, (item_id, qty) in enumerate(visible, start=1)
    ]


def _is_frozen(item_id: str) -> bool:
    """Whether ``item_id`` is a frozen-frog item (grid-sorted last).

    Frozen frogs are trophies: they sort after every live item in the
    inventory. Detection defers to the frogs plugin's ``frozen_species_of``
    (matches ``frog:<species>:frozen``); anything else — live frogs, the
    ``remains`` consolation item, non-frog items — is not frozen. The
    import is lazy so the generic inventory extension never hard-couples
    to the frogs package at load time.
    """
    from plugins.frogs.thaw import frozen_species_of

    return frozen_species_of(item_id) is not None


async def _slot_entry(
    bot: CazzuBot, uid: int, slot: int
) -> tuple[int, str, int] | None:
    """The visible ``(slot, item_id, qty)`` row for ``slot``, or None.

    Uses the same compacted numbering as the view (:func:`_indexed_resolved`),
    so a slot that renders always resolves to the same item here — hidden
    (unresolved) stacks are unreachable instead of addressable-but-empty.
    """
    indexed = await _indexed_resolved(bot, uid)
    return next((row for row in indexed if row[0] == slot), None)


async def _slot_balance(bot: CazzuBot, uid: int, slot: int) -> int:
    """Re-read a slot's stack at consume time (slots are derived, not stored)."""
    entry = await _slot_entry(bot, uid, slot)
    return entry[2] if entry is not None else 0


async def _seasonal_exp(bot: CazzuBot, uid: int) -> int:
    """A member's current-season exp — the metric item consumes grant.

    Frog consumables log their exp straight into ``member_exp_log``
    (``source=FROG``); lifetime on ``member_exp`` is precomputed and only
    resynced by the daily job, so it would read stale right after a
    consume. Reading the seasonal sum (the same measure the item's "On
    consumption" blurb promises) reflects the grant immediately.
    """
    from plugins.experience import db as exp_db

    now = pendulum.now("UTC")
    return await exp_db.seasonal_exp(
        bot.db, uid, now.year, utils.month2season(now.month)
    )
