import os, asyncio
from collections import OrderedDict

import discord
from discord.ext import commands
from tinydb import TinyDB
from db_guild_interface import fetch
from utility import make_simple_embed

from secret import TOKEN
from dev import DEV_MODE

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix='d!' if DEV_MODE else 'c!', owner_id = 92664421553307648, intents=intents)


@bot.event
async def on_ready():
    print(f'Logged in as: {bot.user.name}')
    print(f'With ID: {bot.user.id}')
    print(flush=True)


if __name__ == '__main__':
    bot.db_guild = TinyDB('guild.json')
    bot.db_user = TinyDB('user.json')

    bot.data_to_return = dict()
    for file in os.listdir('cog'):
        if file.endswith('.py'):
            bot.load_extension('cog.' + file[0:-3])

    # Block DMs and other bots
    @bot.check
    async def globally_block_dms(ctx):
        return ctx.guild is not None

    @bot.check
    async def block_all_other_bots(ctx):
        return not ctx.message.author.bot

    bot.run(TOKEN)