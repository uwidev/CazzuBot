import os, asyncio
from collections import OrderedDict

import discord
from discord.ext import commands
from tinydb import TinyDB
from db_guild_interface import fetch
from secret import TOKEN
from utility import make_simple_embed

DEV_MODE = True

bot = commands.Bot(command_prefix='d!' if DEV_MODE else 'c!', owner_id = 92664421553307648)


@bot.event
async def on_ready():
    print(f'Logged in as: {bot.user.name}')
    print(f'With ID: {bot.user.id}')


if __name__ == '__main__':
    bot.db_guild = TinyDB('guild.json')
    bot.db_user = TinyDB('user.json')

    bot.data_to_return = dict()
    for file in os.listdir('cog'):
        if file.endswith('.py'):
            bot.load_extension('cog.' + file[0:-3])

    @bot.check
    async def globally_block_dms(ctx):
        return ctx.guild is not None

    @bot.check
    async def block_all_other_bots(ctx):
        return not ctx.message.author.bot

    @bot.command()
    @commands.is_owner()
    async def reload(ctx, *, ext_name):
        ext = 'cog.' + ext_name
        if ext not in bot.extensions:
            await ctx.send(embed=make_simple_embed('ERROR', 'Extension doesn\'t exist or you can\'t spell!'))
            raise commands.BadArgument
        
        try:
            bot.reload_extension(ext)
            await ctx.send(embed=make_simple_embed('Success', f'{ext_name.capitalize()} has been reloaded'))
        except Exception as e:
            await ctx.send(embed=make_simple_embed('ERROR', 'There appears to be a problem with your code, baka.'))
            raise e

    @bot.command()
    @commands.is_owner()
    async def load(ctx, ext_name):
        ext = ext_name + '.py'
        dir = os.listdir('cog')
        
        if ext in dir:
            try:
                bot.load_extension('cog.' + ext_name)
                await ctx.send(embed=make_simple_embed('Success', f'{ext_name.capitalize()} has been loaded'))
            except Exception as e:
                await ctx.send(embed=make_simple_embed('ERROR', 'Something terrible happened!'))
                raise e
        else:
            await ctx.send(embed=make_simple_embed('ERROR', 'File doesn\'t exist or you can\'t spell!'))

    @bot.command()
    @commands.is_owner()
    async def unload(ctx, ext_name):
        ext = 'cog.' + ext_name
        if ext not in bot.extensions:
            await ctx.send(embed=make_simple_embed('ERROR', 'Extension wasn\'t loaded to begin with!'))
            raise commands.BadArgument
        
        
        dir = os.listdir('cog')
        if ext_name + '.py' in dir:
            try:
                bot.unload_extension('cog.' + ext_name)
                await ctx.send(embed=make_simple_embed('Success', f'{ext_name.capitalize()} has been unloaded'))
            except Exception as e:
                await ctx.send(embed=make_simple_embed('ERROR', 'Something terrible happened!'))
                raise e
        else:
            await ctx.send(embed=make_simple_embed('ERROR', 'Extension doesn\'t exist or you can\'t spell!'))


    bot.run(TOKEN)