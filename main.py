import os
import traceback

import discord
from discord.ext import commands
import tinydb

from secret import TOKEN, OWNER_ID


# Intents need to be set up to let discord know what we want for requests
intents = discord.Intents.default()
intents.message_content = True

# Run bot
bot = commands.Bot('d!', intents=intents, owner_id=OWNER_ID)


@bot.event
async def on_ready():
    print(f'Loading extensions...')

    await load_cogs()

    print(f'Logged in as {bot.user.name}')


async def load_cogs():
    for file in os.listdir('cogs'):
        if file.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{file[:-3]}')
                print(f'{file[:-3]} has been loaded!')
            except Exception as e:
                print(traceback.print_exception(e))
    
    print(bot.extensions)


# turn cog reload into group command with check for admin perms
@commands.check(lambda ctx : ctx.message.author.guild_permissions.administrator)
@bot.group()
async def cog(ctx: commands.Context):
    pass


@cog.command()
async def reload(ctx, *, ext_name):
    ext = 'cogs.' + ext_name
    if ext not in bot.extensions:
        await ctx.send(f"❌ cog {ext_name} does not exist")
    
    try:
        await bot.reload_extension(ext)
        await ctx.send(f"✅ cog {ext_name} has been reloaded")
    except Exception as e:
        await ctx.send(f"❌ cog {ext_name} was found but an error occured (probably within cog code)")


@cog.command()
async def load(ctx, ext_name):
    ext = ext_name + '.py'
    dir = os.listdir('cogs')
    
    if ext in dir:
        try:
            await bot.load_extension('cogs.' + ext_name)
            await ctx.send(f"✅ cog {ext_name} has been loaded")
        except Exception as e:
            await ctx.send(f"❌ cog {ext_name} was found but an error occured (probably within cog code)")
    else:
        await ctx.send(f"❌ cog {ext_name} does not exist")


@cog.command()
async def unload(ctx, ext_name):
    ext = 'cogs.' + ext_name
    if ext not in bot.extensions:
        await ctx.send(f'❌ cog {ext_name} wasn\'t loaded to begin with!')
    
    dir = os.listdir('cogs')
    if ext_name + '.py' in dir:
        try:
            await bot.unload_extension('cogs.' + ext_name)
            await ctx.send(f"✅ cog {ext_name} has been unloaded")
        except Exception as e:
            await ctx.send(f"❌ cog {ext_name} was found but an error occured (probably within cog code)")
    else:
        await ctx.send(f"❌ cog {ext_name} does not exist")


if __name__ == "__main__":
    bot.run(TOKEN)