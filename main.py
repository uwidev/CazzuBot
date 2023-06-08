"""Runs the bot."""
import logging
import os

import discord
from discord.ext import commands
from tinydb import TinyDB

from db_interface import Table
from secret import OWNER_ID, TOKEN


DEFAULT_DATABASE_TABLE = Table.USER_EXPERIENCE.name


# Setup logging
discord.utils.setup_logging()  # Log to console

handler_file = logging.FileHandler(
    filename="logs/discord.log", encoding="utf-8", mode="w"
)

discord.utils.setup_logging(handler=handler_file)

_log = logging.getLogger(__name__)


# Intents need to be set up to let discord know what we want for request
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot("d!", intents=intents, owner_id=OWNER_ID)


@bot.event
async def on_ready():
    _log.info("Logged in as %s", bot.user.name)


async def load_extensions():
    for file in os.listdir("cogs"):
        if file.endswith(".py"):
            try:
                await bot.load_extension(f"cogs.{file[:-3]}")
                _log.info("|\t> %s has been loaded!", file[:-3])
            except (
                commands.ExtensionNotFound,
                commands.ExtensionAlreadyLoaded,
                commands.NoEntryPointError,
                commands.ExtensionFailed,
            ) as err:
                _log.error(err)


# turn cog reload into group command with check for admin perms
@commands.check(lambda ctx: ctx.message.author.id == bot.owner_id)
@bot.group()
async def cog(ctx: commands.Context):
    pass


@cog.command()
async def reload(ctx, *, ext_name):
    ext = "cogs." + ext_name
    if ext not in bot.extensions:
        await ctx.send(f"❌ cog {ext_name} does not exist")

    try:
        await bot.reload_extension(ext)
        await ctx.send(f"✅ cog {ext_name} has been reloaded")
    except (
        commands.ExtensionNotLoaded,
        commands.ExtensionNotFound,
        commands.NoEntryPointError,
        commands.ExtensionFailed,
    ) as err:
        _log.error(err)


@cog.command()
async def load(ctx, ext_name):
    ext = ext_name + ".py"
    dir_cog = os.listdir("cogs")

    if ext in dir_cog:
        try:
            await bot.load_extension("cogs." + ext_name)
            await ctx.send(f"✅ cog {ext_name} has been loaded")
        except (
            commands.ExtensionNotFound,
            commands.ExtensionAlreadyLoaded,
            commands.NoEntryPointError,
            commands.ExtensionFailed,
        ) as err:
            _log.error(err)
    else:
        await ctx.send(f"❌ cog {ext_name} does not exist")


@cog.command()
async def unload(ctx, ext_name):
    ext = "cogs." + ext_name
    if ext not in bot.extensions:
        await ctx.send(f"❌ cog {ext_name} wasn't loaded to begin with!")

    dir_cog = os.listdir("cogs")
    if ext_name + ".py" in dir_cog:
        try:
            await bot.unload_extension("cogs." + ext_name)
            await ctx.send(f"✅ cog {ext_name} has been unloaded")
        except (commands.ExtensionNotFound, commands.ExtensionNotLoaded) as err:
            _log.error(err)
    else:
        await ctx.send(f"❌ cog {ext_name} does not exist")


async def setup():
    _log.info("Loading database...")
    bot.db = TinyDB("db.json")
    bot.db.default_table_name = DEFAULT_DATABASE_TABLE

    _log.info("Loading extensions...")
    await load_extensions()


if __name__ == "__main__":
    bot.setup_hook = setup
    bot.run(TOKEN, log_handler=None)  # Ignore built-in logger
