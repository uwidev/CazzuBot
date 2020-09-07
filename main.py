import os, asyncio
from collections import OrderedDict

import discord
from discord.ext import commands
from tinydb import TinyDB
from db_guild_interface import fetch
from secret import TOKEN


bot = commands.Bot(command_prefix='d!', owner_id = 92664421553307648)


@bot.event
async def on_ready():
    print(f'Logged in as: {bot.user.name}')
    print(f'With ID: {bot.user.id}')

if __name__ == '__main__':
    for file in os.listdir('cog'):
        if file.endswith('.py'):
            bot.load_extension('cog.' + file[0:-3])

    bot.db_guild = TinyDB('guild.json')
    bot.db_user = TinyDB('user.json')

    bot.run(TOKEN)
