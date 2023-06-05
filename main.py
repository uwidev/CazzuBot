import os
import logging

import discord
from discord.ext import commands
from tinydb import TinyDB

from secret import TOKEN, OWNER_ID


DEFAULT_DATABASE_TABLE = 'user'


# Setup logging
discord.utils.setup_logging()  # Log to console

handler_file = logging.FileHandler(filename='discord.log',
                                   encoding='utf-8',
                                   mode='w')

_log = logging.getLogger(__name__)
_log.addHandler(handler_file)

# Intents need to be set up to let discord know what we want for requests
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot('d!',
                   intents=intents,
                   owner_id=OWNER_ID)


@bot.event
async def on_ready():
    logging.info('Loading extensions...')

    await load_cogs()

    logging.info('Logged in as %s', bot.user.name)


async def load_cogs():
    for file in os.listdir('cogs'):
        if file.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{file[:-3]}')
                logging.info('%s has been loaded!', file[:-3])
            except (commands.ExtensionNotFound, 
                    commands.ExtensionAlreadyLoaded,
                    commands.NoEntryPointError,
                    commands.ExtensionFailed) as err:
                logging.error(err)


# turn cog reload into group command with check for admin perms
@commands.check(lambda ctx: ctx.message.author.guild_permissions.administrator)
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
    except (commands.ExtensionNotLoaded, commands.ExtensionNotFound,
            commands.NoEntryPointError, commands.ExtensionFailed) as err:
        logging.error(err)


@cog.command()
async def load(ctx, ext_name):
    ext = ext_name + '.py'
    dir_cog = os.listdir('cogs')
    
    if ext in dir_cog:
        try:
            await bot.load_extension('cogs.' + ext_name)
            await ctx.send(f"✅ cog {ext_name} has been loaded")
        except (commands.ExtensionNotFound, 
                commands.ExtensionAlreadyLoaded,
                commands.NoEntryPointError,
                commands.ExtensionFailed) as err:
            logging.error(err)
    else:
        await ctx.send(f"❌ cog {ext_name} does not exist")


@cog.command()
async def unload(ctx, ext_name):
    ext = 'cogs.' + ext_name
    if ext not in bot.extensions:
        await ctx.send(f'❌ cog {ext_name} wasn\'t loaded to begin with!')
    
    dir_cog = os.listdir('cogs')
    if ext_name + '.py' in dir_cog:
        try:
            await bot.unload_extension('cogs.' + ext_name)
            await ctx.send(f"✅ cog {ext_name} has been unloaded")
        except (commands.ExtensionNotFound, 
                commands.ExtensionNotLoaded) as err:
            logging.error(err)
    else:
        await ctx.send(f"❌ cog {ext_name} does not exist")


if __name__ == "__main__":
    bot.db = TinyDB('db.json')
    bot.db.default_table_name = DEFAULT_DATABASE_TABLE

    bot.run(TOKEN, log_handler=None)  # Ignore built-in logger
