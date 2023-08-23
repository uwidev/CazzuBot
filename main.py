"""Runs the bot.

TODO: Developing a new cog is too powerful(?) when interacting with the dabase.
db_interface should have dedicated functions for adding a new setting, rather than
being able to add whatever data onto whatever table.

Should be a lot more straight-forward on extending the bot.
"""
import datetime
import getpass
import logging
import os
import sys
import time

import discord
import pendulum
import psycopg2
from discord.ext import commands
from discord.utils import _ColourFormatter, stream_supports_colour

from secret import OWNER_ID, TOKEN

# from src import task
from src.settings import Guild


# DEFAULT_DATABASE_TABLE = Table.USER_EXPERIENCE.name
EXTENSIONS_IMPORT_PATH = r"ext"
EXTENSIONS_PATH = r"ext"
DATABASE_HOST = "192.168.1.2"
DATABASE_NAME = "ubuntu"
DATABASE_USER = "ubuntu"


_log = logging.getLogger(__name__)


# Intents need to be set up to let discord know what we want for request
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot("d!", intents=intents, owner_id=OWNER_ID)


def set_logging():
    """Write info logging to console and debug logging to file."""

    def timetz(*args):
        return pendulum.now(tz="UTC").timetuple()

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    file_hanndler = logging.FileHandler(
        filename="logs/discord.log", encoding="utf-8", mode="w"
    )
    file_hanndler.setLevel(logging.DEBUG)

    dt_fmt = "%Y-%m-%d %H:%M:%S"
    file_formatter = logging.Formatter(
        "[{asctime}] [{levelname:<8}] {name}: {message}", dt_fmt, style="{"
    )

    console_formatter = file_formatter
    console_formatter = (  # TIME CONVERTER DOES NOT WORK ON _ColourFormatter()
        _ColourFormatter()  # NEEDS INVESTIGATION | FIXED, UPDATE TO NEWEST POWERSHELL
        if stream_supports_colour(console_handler.stream)
        else file_formatter
    )

    console_formatter.converter = time.gmtime
    file_formatter.converter = time.gmtime

    console_handler.setFormatter(console_formatter)
    file_hanndler.setFormatter(file_formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_hanndler)


@bot.event
async def on_ready():
    _log.info("Logged in as %s", bot.user.name)


async def load_extensions():
    for file in os.listdir(EXTENSIONS_PATH):
        if file.endswith(".py"):
            try:
                await bot.load_extension(f"{EXTENSIONS_IMPORT_PATH}.{file[:-3]}")
                _log.info("|\t> loaded %s!", file[:-3])
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
    ext = f"{EXTENSIONS_IMPORT_PATH}.{ext_name}"
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
    extensions = os.listdir(EXTENSIONS_PATH)

    if ext_name not in map(lambda x: x[:-3], extensions):
        await ctx.send(f"❌ cog {ext_name} does not exist")
        return

    try:
        await bot.load_extension(f"{EXTENSIONS_IMPORT_PATH}.{ext_name}")
        await ctx.send(f"✅ cog {ext_name} has been loaded")
    except (
        commands.ExtensionNotFound,
        commands.ExtensionAlreadyLoaded,
        commands.NoEntryPointError,
        commands.ExtensionFailed,
    ) as err:
        _log.error(err)


@cog.command()
async def unload(ctx, ext_name):
    ext = f"{EXTENSIONS_IMPORT_PATH}.{ext_name}"

    if ext not in bot.extensions:
        await ctx.send(f"❌ cog {ext_name} wasn't loaded to begin with!")
        return

    extensions = os.listdir(EXTENSIONS_PATH)
    if ext_name + ".py" not in extensions:
        await ctx.send(f"❌ cog {ext_name} does not exist")
        return

    try:
        await bot.unload_extension(f"{EXTENSIONS_IMPORT_PATH}.{ext_name}")
        await ctx.send(f"✅ cog {ext_name} has been unloaded")
    except (commands.ExtensionNotFound, commands.ExtensionNotLoaded) as err:
        _log.error(err)


def postgre_connect():
    pw = getpass.getpass()

    try:
        conn = psycopg2.connect(
            dbname=DATABASE_NAME,
            user=DATABASE_USER,
            host=DATABASE_HOST,
            password=pw,
        )
    except psycopg2.Error as err:
        _log.error(err)
        return None
    else:
        _log.info(
            'Connection to database "%s" as user "%s" at ' 'host "%s" successful!',
            DATABASE_NAME,
            DATABASE_USER,
            DATABASE_HOST,
        )
        return conn


async def setup():
    _log.info("Connnecting to database...")
    bot.db = postgre_connect()
    if not bot.db:
        _log.error("Unable to connect to database.")
        sys.exit(1)

    _log.info("Setting up default settings...")
    bot.guild_defaults = Guild()

    _log.info("Loading extensions...")
    await load_extensions()

    bot.guild_defaults.lock()

    return 0

    # _log.info("Loading tasks...")
    # await task.all(bot.db)

    # _log.info("Resolving tasks...")
    # _log.warning("Task resolution not yet implemented!")


if __name__ == "__main__":
    set_logging()
    bot.setup_hook = setup
    bot.run(TOKEN, log_handler=None)  # Ignore built-in logger
    _log.info("Keyboard interrupt detected!")
    _log.info("Closing the database...")
    bot.db.close()
    _log.info("Database closed")
