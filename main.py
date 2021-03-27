import os, asyncio
from collections import OrderedDict

import discord
from discord.ext import commands
from tinydb import TinyDB
from db_guild_interface import fetch
from utility import make_simple_embed_t

from secret import TOKEN
from dev import DEV_MODE

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix='d!' if DEV_MODE else 'c!', owner_id = 92664421553307648, intents=intents)


@bot.event
async def on_ready():
    print(f'Logged in as: {bot.user.name}')
    print(f'With ID: {bot.user.id}')


if __name__ == '__main__':
    # guild.json stores all the configuration of the guild
    bot.db_guild = TinyDB('guild.json')

    # user.json stores the data of all users
    #
    # This does not differentiate between USERS and MEMBERS IN A GUILD. 
    # If you want to let others use this bot in other servers, you must differentiate
    # members of a guild and regular users (global scope, guild scope).
    #
    # As a matter of fact, ranks.py and levels.py do not make sense because ranks are,
    # at the moment, globally scoped and ranks are scoped per guild.
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