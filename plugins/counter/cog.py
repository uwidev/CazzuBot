"""Counter plugin — controller: baka button view, create command, expiry.

Single-guild port of v1's ``ext/counter.py``. A registered counter message
carries a persistent button; each press increments the count, the footer shows
who "did a baka", and a 2-hour expiry task (tag ``counter``) resets the footer.
The button view is re-attached to every existing counter message on boot via
``on_load`` + ``bot.add_view``.
"""

import logging
from typing import Any

import discord
import pendulum
from discord.ext import commands

from cazzubot import utils
from cazzubot.bot import CazzuBot

from . import db

_log = logging.getLogger(__name__)

FROG = "https://files.catbox.moe/qo7bkv.gif"
POGFROG = "https://files.catbox.moe/k5qvvd.gif"
BAKAPPLE = "https://files.catbox.moe/ogq9lq.gif"
BORED = "https://files.catbox.moe/0ex005.gif"
CIRNO_HELP = "<:cirnoHelp:695126168227151954>"

NO_BAKAS_TEXT = "There are no bakas as of recently..."


class CounterCog(commands.Cog):
    """Baka button counter."""

    def __init__(self, bot: CazzuBot) -> None:
        self.bot = bot

    @commands.hybrid_group()
    async def counter(self, _ctx: commands.Context[CazzuBot]) -> None:
        """Baka counter management."""

    @counter.command(name="create")
    async def counter_create(
        self, ctx: commands.Context[CazzuBot]
    ) -> None:
        """Create the baka counter message in this channel."""
        embed = utils.prepare_embed(
            "Number of times people have touched the baka button", "> 0"
        )
        embed.set_thumbnail(url=BORED)
        embed.set_footer(text=NO_BAKAS_TEXT, icon_url=FROG)
        msg = await ctx.send(embed=embed, view=CounterView(self.bot))
        await db.create(self.bot.db, msg.id)


class CounterView(discord.ui.View):
    """Persistent baka button — one press = one count."""

    def __init__(self, bot: CazzuBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    async def _schedule_expiry(self, mid: int, cid: int) -> None:
        """Reset the 2h footer timer, replacing any pending wipe."""
        for task in await self.bot.scheduler.get("counter", {"mid": mid}):
            await self.bot.scheduler.drop(task.id)
        await self.bot.scheduler.add(
            "counter",
            pendulum.now("UTC").add(hours=2),
            {"mid": mid, "cid": cid},
        )

    @discord.ui.button(
        emoji=CIRNO_HELP,
        label="Baka",
        style=discord.ButtonStyle.primary,
        custom_id="counter:baka",
    )
    async def baka(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[Any],
    ) -> None:
        if interaction.message is None:
            return
        mid = interaction.message.id

        # atomic increment — no lost updates under concurrent presses
        count_new = await db.bump_count(self.bot.db, mid)
        if count_new is None:
            await interaction.response.send_message(
                "This is not a baka counter anymore.", ephemeral=True
            )
            return

        await db.record_baka(
            self.bot.db,
            mid,
            interaction.user.id,
            interaction.user.display_name,
            pendulum.now("UTC").to_iso8601_string(),
        )

        names = await db.recent_bakas(self.bot.db, mid)

        embed = utils.prepare_embed(
            "Number of times people have touched the baka button",
            f"> {count_new}",
        )
        embed.set_thumbnail(url=BAKAPPLE)
        if names:
            embed.set_footer(
                text=f"{', '.join(names)} had recently done a baka!",
                icon_url=POGFROG,
            )
        else:
            embed.set_footer(text=NO_BAKAS_TEXT, icon_url=FROG)

        await interaction.response.edit_message(embed=embed)

        if interaction.channel_id is None:
            return
        await self._schedule_expiry(mid, interaction.channel_id)


async def on_counter_expire(
    bot: CazzuBot, payload: dict[str, Any]
) -> None:
    """Scheduler handler for tag ``counter`` — reset the embed footer."""
    cid, mid = payload["cid"], payload["mid"]
    # clear the recent-baka list even if the message is already gone
    await db.clear_bakas(bot.db, mid)

    channel = bot.get_channel(cid)
    if not isinstance(
        channel,
        (
            discord.TextChannel,
            discord.VoiceChannel,
            discord.StageChannel,
            discord.Thread,
            discord.DMChannel,
            discord.GroupChannel,
        ),
    ):
        return
    try:
        msg = await channel.fetch_message(mid)
    except discord.NotFound:
        return

    embed = msg.embeds[-1]
    embed.set_footer(text=NO_BAKAS_TEXT, icon_url=FROG)
    embed.set_thumbnail(url=BORED)
    await msg.edit(embed=embed)
