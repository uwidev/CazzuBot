"""Counter plugin — the "baka button" counter.

Single-guild port of v1's ``ext/counter.py`` + ``src/db/counter.py``. A
registered counter message carries a persistent button; each press increments
the count, the footer shows who "did a baka", and a 2-hour expiry task
(tag ``counter``) resets the footer. The button view is re-attached to every
existing counter message on boot via ``on_load`` + ``bot.add_view``.
"""

import logging
from typing import Any

import discord
import pendulum
from discord.ext import commands

from cazzubot import Plugin, utils
from cazzubot.bot import CazzuBot
from typing_extensions import override

_log = logging.getLogger(__name__)

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS counter (
		mid   INTEGER PRIMARY KEY,
		count INTEGER NOT NULL DEFAULT 0
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS counter_baka (
		mid        INTEGER NOT NULL,
		uid        INTEGER NOT NULL,
		name       TEXT NOT NULL,
		updated_at TEXT NOT NULL,
		PRIMARY KEY (mid, uid)
	)
	""",
]

FROG = "https://files.catbox.moe/qo7bkv.gif"
POGFROG = "https://files.catbox.moe/k5qvvd.gif"
BAKAPPLE = "https://files.catbox.moe/ogq9lq.gif"
BORED = "https://files.catbox.moe/0ex005.gif"
CIRNO_HELP = "<:cirnoHelp:695126168227151954>"

NO_BAKAS_TEXT = "There are no bakas as of recently..."


async def on_counter_expire(
    bot: CazzuBot, payload: dict[str, Any]
) -> None:
    """Scheduler handler for tag ``counter`` — reset the embed footer."""
    cid, mid = payload["cid"], payload["mid"]
    # clear the recent-baka list even if the message is already gone
    await bot.db.execute("DELETE FROM counter_baka WHERE mid = ?", mid)

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
        await self.bot.db.execute(
            "UPDATE counter SET count = count + 1 WHERE mid = ?", mid
        )
        row = await self.bot.db.fetchone(
            "SELECT count FROM counter WHERE mid = ?", mid
        )
        if row is None:
            await interaction.response.send_message(
                "This is not a baka counter anymore.", ephemeral=True
            )
            return
        count_new = row["count"]

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO counter_baka (mid, uid, name, updated_at)"
            + " VALUES (?, ?, ?, ?)",
            mid,
            interaction.user.id,
            interaction.user.display_name,
            pendulum.now("UTC").to_iso8601_string(),
        )

        rows = await self.bot.db.fetchall(
            "SELECT name FROM counter_baka WHERE mid = ?"
            + " ORDER BY updated_at DESC",
            mid,
        )
        names = [r["name"] for r in rows]

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
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO counter (mid, count) VALUES (?, 0)",
            msg.id,
        )


class CounterPlugin(Plugin):
    name = "counter"
    schema = SCHEMA
    cogs = [CounterCog]
    scheduled = {"counter": on_counter_expire}

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Re-attach the persistent button to every existing counter."""
        rows = await bot.db.fetchall("SELECT mid FROM counter")
        for row in rows:
            bot.add_view(CounterView(bot), message_id=row["mid"])


plugin = CounterPlugin()
