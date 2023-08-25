"""Runs the bot.

TODO: Developing a new cog is too powerful(?) when interacting with the dabase.
db_interface should have dedicated functions for adding a new setting, rather than
being able to add whatever data onto whatever table.

Should be a lot more straight-forward on extending the bot.
"""
import asyncio
import getpass
import logging
import os
import sys
import time

import asyncpg
import discord
import pendulum
from asyncpg import Pool
from discord.ext import commands
from discord.utils import _ColourFormatter, stream_supports_colour

from secret import OWNER_ID, TOKEN

# from src import task
from src.settings import Guild


EXTENSIONS_IMPORT_PATH = r"ext"
EXTENSIONS_PATH = r"ext"

# DEFAULT_DATABASE_TABLE = Table.USER_EXPERIENCE.name
DATABASE_HOST = "192.168.1.2"
DATABASE_NAME = "ubuntu"
DATABASE_USER = "ubuntu"


_log = logging.getLogger(__name__)


class CazzuBot(commands.Bot):
    def __init__(self, *args, pool: Pool, **kwargs):
        super().__init__(*args, **kwargs)
        self.pool = pool

    async def on_ready(
        self,
    ):
        _log.info("Logged in as %s", self.user.name)

    async def load_extensions(
        self,
    ):
        for file in os.listdir(EXTENSIONS_PATH):
            if file.endswith(".py"):
                try:
                    await self.load_extension(f"{EXTENSIONS_IMPORT_PATH}.{file[:-3]}")
                    _log.info("|\t> loaded %s!", file[:-3])
                except (
                    commands.ExtensionNotFound,
                    commands.ExtensionAlreadyLoaded,
                    commands.NoEntryPointError,
                    commands.ExtensionFailed,
                ) as err:
                    _log.error(err)

    async def postgre_connect(self) -> Pool:
        pw = getpass.getpass()

        try:
            pool = await asyncpg.create_pool(
                database=DATABASE_NAME,
                user=DATABASE_USER,
                host=DATABASE_HOST,
                password=pw,
            )
        except Exception as err:
            _log.error(err)
            _log.error("Unable to connect to database.")
            sys.exit(1)
        else:
            _log.info(
                'Connection to database "%s" as user "%s" at host "%s" successful!',
                DATABASE_NAME,
                DATABASE_USER,
                DATABASE_HOST,
            )
            return pool

    async def setup_hook(self) -> None:
        _log.info("Loading extensions...")
        await self.load_extensions()

        return 0

        # _log.info("Loading tasks...")
        # await task.all(bot.pool)

        # _log.info("Resolving tasks...")
        # _log.warning("Task resolution not yet implemented!")


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


async def main():
    set_logging()

    # Intents need to be set up to let discord know what we want for request
    intents = discord.Intents.default()
    intents.message_content = True

    pw = getpass.getpass()

    async with asyncpg.create_pool(
        database=DATABASE_NAME, user=DATABASE_USER, host=DATABASE_HOST, password=pw
    ) as pool:
        async with CazzuBot("d!", pool=pool, intents=intents, owner_id=OWNER_ID) as bot:
            await bot.start(TOKEN)  # Ignore built-in logger


if __name__ == "__main__":
    asyncio.run(main())
