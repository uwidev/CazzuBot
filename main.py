"""Runs the bot.

TODO: Convert all db operations to asyncio-aware.
"""
import logging
import os

import discord
from aiotinydb import AIOTinyDB
from aiotinydb.storage import AIOJSONStorage
from discord.ext import commands

import src.task_manager as tmanager
from secret import OWNER_ID, TOKEN
from src.aio_middleware_patch import AIOSerializationMiddleware
from src.serializers import (
    ModLogStatusSerializer,
    ModLogtypeSerializer,
    PDateTimeSerializer,
)


# DEFAULT_DATABASE_TABLE = Table.USER_EXPERIENCE.name
EXTENSIONS_IMPORT_PATH = r"src.extensions"
EXTENSIONS_PATH = r"src/extensions"


# Setup logging
discord.utils.setup_logging()  # Log to console

handler_file = logging.FileHandler(
    filename="logs/discord.log", encoding="utf-8", mode="w"
)

discord.utils.setup_logging(handler=handler_file, level=logging.DEBUG)
# debug still shows up on console, needs to be file ONLY

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
}


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


async def setup():
    _log.info("Loading database...")
    serialization = AIOSerializationMiddleware(AIOJSONStorage)
    for s in serializers.items():
        serialization.register_serializer(s[0], s[1])
    bot.db = AIOTinyDB("db.json", storage=serialization)
    # bot.db.default_table_name = DEFAULT_DATABASE_TABLE

    _log.info("Loading extensions...")
    await load_extensions()

    _log.info("Loading tasks...")
    await tmanager.get_tasks(bot.db)

    _log.info("Resolving tasks...")
    _log.warning("Task resolution not yet implemented!")


if __name__ == "__main__":
    bot.setup_hook = setup
    bot.run(TOKEN, log_handler=None)  # Ignore built-in logger
