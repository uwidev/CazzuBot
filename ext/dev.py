"""Developer commands to run during operation."""

import asyncio
import logging
import os
import re
from collections import defaultdict
from typing import TYPE_CHECKING

import discord
import pendulum
from discord.ext import commands

# from tinydb import Query, TinyDB
from src import db


if TYPE_CHECKING:
    from main import CazzuBot


# import src.db_interface as dbi
# from src.serializers import TestEnum


_log = logging.getLogger(__name__)


class Dev(commands.Cog):
    def __init__(self, bot):
        self.bot: CazzuBot = bot
        # self.bot.tinydb = TinyDB("user.json")

    def cog_check(self, ctx):
        return ctx.author.id == self.bot.owner_id

    @commands.command()
    async def test(self, ctx: commands.Context):
        await ctx.send("jierabnhgbnaljkgn")


    # async def tinydb_frog_cap_migrate(self):
    #     _log.info("Beginning database insert...")
    #     async with self.bot.pool.acquire() as con:
    #         async with con.transaction():
    #             for user in iter(self.bot.tinydb):
    #                 captures = user["frogs_lifetime"]
    #                 uid = user["id"]
    #                 _log.info(f"Inserting {uid=} | {captures=}")
    #                 await con.execute(
    #                     """
    #                     UPDATE member_frog
    #                     SET capture = $1
    #                     WHERE uid = $2
    #                     """,
    #                     captures,
    #                     uid,
    #                 )
    #     _log.info("====== Done =======")

    @commands.group()
    async def story(self, ctx):
        pass

    @story.command(name="compile")
    async def story_compile(self, ctx):
        """Saves all message in a .txt file as one long message. Also summarizes the contributions.
        File name will be the same as the channel name.
        """
        channel = ctx.channel
        contributions = 0
        emoji = re.compile(r"(<a?:[a-zA-Z0-9\_]+:[0-9]+>)")
        contributors = defaultdict(int)

        async with channel.typing():
            if not os.path.isdir("story"):
                os.makedirs("story")

            participants = defaultdict(int)
            with open(f"story/{channel.name}.txt", mode="w", encoding="utf-8") as file:
                async for message in channel.history(
                    limit=None, before=ctx.message, oldest_first=True
                ):
                    contributors[message.author.name] += 1

                    file.write(f"{message.content} ")
                    contributions += 1
                    participants[message.author] += 1

                with open(
                    f"story/{channel.name}-contibutors.txt", mode="w", encoding="utf-8"
                ) as file:
                    file.write(
                        f".\n.\n.\n__**Total contributions: {contributions}**__\n"
                    )

                    i = 0
                    for item in sorted(
                        contributors.items(), key=lambda x: x[1], reverse=True
                    ):
                        percent = item[1] / contributions
                        if i < 5:
                            file.write(f"**{item[0]}: {item[1]} ({percent:.2%})**\n")
                        else:
                            file.write(f"{item[0]}: {item[1]} ({percent:.2%})\n")
                        i += 1

            # msg = await channel.send('🎉 Done compiling 🎉')
            # await msg.delete(delay=3)
            await ctx.message.delete()

    @story.command()
    async def write(self, ctx, file_name):
        """Given a existing file name from a compiled story, writes the entire story."""
        await ctx.send(f"```fix\n>>> {file_name} <<<```")
        async with ctx.channel.typing():
            with open(f"story/{file_name}.txt", encoding="utf-8") as file:
                while True:
                    i = 0
                    to_append = ""
                    to_print = ""
                    eof_reached = 0

                    while i <= 1900 or to_append != " ":
                        to_append = file.read(1)

                        if not to_append:
                            # print('>>> reached EOF')
                            eof_reached = 1
                            break

                        to_print += to_append
                        i += 1

                    try:
                        await ctx.send(to_print)
                        await asyncio.sleep(2)
                    except discord.errors.HTTPException:
                        pass
                    if eof_reached == 1:
                        break

            with open(f"story/{file_name}-contibutors.txt", encoding="utf-8") as file:
                while True:
                    i = 0
                    to_append = ""
                    to_print = ""
                    eof_reached = 0

                    while i <= 1900 or to_append != " ":
                        to_append = file.read(1)

                        if not to_append:
                            # print('>>> reached EOF')
                            eof_reached = 1
                            break

                        to_print += to_append
                        i += 1

                    # _log.info('going to print {}'.format(to_print))
                    await ctx.send(to_print)
                    if eof_reached == 1:
                        break
                    await asyncio.sleep(2)

        await ctx.message.delete()


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
