import os, asyncio
from collections import OrderedDict

import discord
from discord.ext import commands
from tinydb import TinyDB
from db_guild_interface import fetch
from secret import TOKEN

DEV_MODE = False

bot = commands.Bot(command_prefix='d!' if DEV_MODE else 'c!', owner_id = 92664421553307648)


@bot.event
async def on_ready():
    print(f'Logged in as: {bot.user.name}')
    print(f'With ID: {bot.user.id}')

if __name__ == '__main__':
    bot.db_guild = TinyDB('guild.json')
    bot.db_user = TinyDB('user.json')

    for file in os.listdir('cog'):
        if file.endswith('.py'):
            bot.load_extension('cog.' + file[0:-3])

    bot.run(TOKEN)

    @bot.check
    async def globally_block_dms(ctx):
        return ctx.guild is not None

    @bot.check
    async def block_all_other_bots(ctx):
        return not ctx.message.author.bot