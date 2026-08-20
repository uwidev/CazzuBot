"""Inventory plugin extension — the /inventory grid command."""

import hikari
import lightbulb

from cazzubot import utils
from cazzubot.inventory import ItemView

loader = lightbulb.Loader()

_COLOR = hikari.Color.from_hex_code("#a2dcf7")


@loader.command()
class Inventory(
    lightbulb.SlashCommand,
    name="inventory",
    description="Show a member's numbered inventory across every item type.",
):
    """Show a member's full inventory in a numbered inline-emoji grid.

    Each slot is numbered 1..N (deterministic ``ORDER BY item`` order, so
    the number is stable across views and a future ``/inventory consume
    <slot>`` can address it by re-computing the same order). Items group
    under their namespace (e.g. FROGS); unregistered namespaces degrade to
    their raw key rather than crashing.
    """

    user = lightbulb.user("user", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the inventory grid embed."""
        bot = utils.bot_from(ctx)
        target = self.user or ctx.member or ctx.user
        indexed = await bot.inventory.rows_indexed(target.id)
        embed = _build_grid(bot, indexed, target)
        await ctx.respond(embed=embed)


def _build_grid(
    bot: object,
    indexed: list[tuple[int, str, int]],
    target: hikari.PartialUser,
) -> hikari.Embed:
    """The inventory embeds: numbered inline-emoji grid across namespaces."""
    embed = hikari.Embed(color=_COLOR)
    embed.set_author(name=f"{target.display_name}'s Inventory")
    if not indexed:
        embed.description = "Your inventory is empty."
        return embed

    current: str | None = None
    for slot, item, qty in indexed:
        prefix = item.split(":", 1)[0]
        if prefix != current:
            embed.add_field(name="", value=f"**{prefix.upper()}**")
            current = prefix
        view = _render(bot, prefix, item, qty)
        embed.add_field(
            name=str(slot),
            value=f"{view.icon} ×{qty}",
            inline=True,
        )
    return embed


def _render(bot: object, prefix: str, item: str, qty: int) -> ItemView:
    """The namespace renderer for a slot, falling back to the raw key."""
    inventory_service = getattr(bot, "inventory", None)
    if inventory_service is None:
        return ItemView(icon="", label=item)
    return inventory_service.renderer_for(prefix)(item, qty)
