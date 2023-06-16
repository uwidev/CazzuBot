"""Runs the bot.

TODO: Developing a new cog is too powerful when interacting with the dabase.
db_interface should have dedicated functions for adding a new setting, rather than
being able to add whatever data onto whatever table.

Should be a lot more straight-forward on extending the bot.
"""
import logging
import os
import time

import discord
import pendulum
from aiotinydb import AIOTinyDB
from aiotinydb.storage import AIOJSONStorage
from discord.ext import commands
from discord.utils import _ColourFormatter, stream_supports_colour

from secret import OWNER_ID, TOKEN
from src import task_manager as tmanager
from src.aio_middleware_patch import AIOSerializationMiddleware
from src.serializers import (
    GuildSettingScopeSerializer,
    ModLogStatusSerializer,
    ModLogtypeSerializer,
    ModSettingNameSerializer,
    PDateTimeSerializer,
)


# DEFAULT_DATABASE_TABLE = Table.USER_EXPERIENCE.name
EXTENSIONS_IMPORT_PATH = r"ext"
EXTENSIONS_PATH = r"ext"


_log = logging.getLogger(__name__)


# Intents need to be set up to let discord know what we want for request
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot("d!", intents=intents, owner_id=OWNER_ID)


# Serializers
serializers = {
    PDateTimeSerializer(): "PDateTime",
    ModLogtypeSerializer(): "ModLogType",
    ModLogStatusSerializer(): "ModLogStatus",
    GuildSettingScopeSerializer(): "SettingScope",
    ModSettingNameSerializer(): "ModSetting",
}


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
        _ColourFormatter()  # NEEDS INVESTIGATION
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


def load_serializers():
    serialization = AIOSerializationMiddleware(AIOJSONStorage)

    for s in serializers.items():
        serialization.register_serializer(s[0], s[1])
        _log.info("|\t> %s has been loaded!", s[1])

    return serialization


async def setup():
    _log.info("Loading database serializers...")
    serialization = load_serializers()

    _log.info("Loading database...")
    bot.db = AIOTinyDB("db.json", storage=serialization)

    _log.info("Loading extensions...")
    await load_extensions()

    _log.info("Loading tasks...")
    await tmanager.get_tasks(bot.db)

    _log.info("Resolving tasks...")
    _log.warning("Task resolution not yet implemented!")


if __name__ == "__main__":
    set_logging()
    bot.setup_hook = setup
    bot.run(TOKEN, log_handler=None)  # Ignore built-in logger
