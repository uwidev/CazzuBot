import discord
from discord.ext import commands

import re

from typing import List, TYPE_CHECKING
from collections import defaultdict
import logging

from src import db

if TYPE_CHECKING:
    from main import CazzuBot

_log = logging.getLogger(__name__)


class Inktober(commands.Cog):
    submission_keyword = re.compile(r"inktober\s+day\s+\d\d?")

    def __init__(self, bot):
        self.bot: CazzuBot = bot

    def cog_check(self, ctx):
        return ctx.author.id == self.bot.owner_id

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """React to message if valid Inktober submission."""
        gid = message.guild.id
        cid = message.channel.id
        watching_cid = await db.guild.get_inktober_cid(self.bot.pool, gid, cid)

        if message.channel.id != watching_cid:
            return

        _log.info("Message found in iktober channel")
        found = self.submission_keyword.search(message.content.lower())
        if found:
            _log.info("Message contents match submission criteria")
            if message.attachments:
                _log.info("Message contains attachments. Submission approved!")
                await message.add_reaction("👍")

    @commands.command()
    async def scrape_inktober(
        self, ctx: commands.Context, ch: discord.TextChannel = None
    ):
        """Scrape a specific channel for inktober submissions.

        TODO: Actually download the images and potentially generate a report,
        perhaps export said report to a file.
        """
        if ch is None:
            ch = ctx.channel

        msg: discord.Message
        # submissions: Dict[int, Dict[int, discord.Attachment]] = dict(dict())
        submissions: defaultdict[int, defaultdict[int, List[discord.Attachment]]] = (
            defaultdict(lambda: defaultdict(list))
        )

        async for msg in ch.history(limit=None, oldest_first=True):
            found = self.submission_keyword.search(msg.content.lower())
            if found and msg.attachments:
                _, day = found.group(0).split()
                day = int(day)
                if day > 0 and day < 31:
                    # do stuff
                    submissions[msg.author.id][day] = msg.attachments

        # print summary... and do stuff?
        for user, day_attach in submissions.items():
            for day, attach in day_attach.items():
                _log.info(f"{user} submitted on day {day}")

    @commands.command()
    async def register_inktober(
        self, ctx: commands.Context, ch: discord.TextChannel = None
    ):
        if not ch:
            ch = ctx.channel

        gid = ctx.guild.id
        cid = ctx.channel.id
        await db.guild.set_inktober_cid(self.bot.pool, gid, cid)


async def setup(bot: commands.Bot):
    await bot.add_cog(Inktober(bot))
