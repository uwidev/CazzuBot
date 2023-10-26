"""Runs the bot."""
import argparse
import asyncio
import getpass
import logging
import time

import asyncpg
import discord
import pendulum
from asyncpg import Connection
from discord.utils import _ColourFormatter, stream_supports_colour

from secret import OWNER_ID, TOKEN
from src.cazzubot import CazzuBot
from src.db.table import ModlogStatusEnum, ModlogTypeEnum


EXTENSIONS_PATH = r"ext"

# DEFAULT_DATABASE_TABLE = Table.USER_EXPERIENCE.name
DATABASE_HOST = "192.168.1.2"
DATABASE_NAME = "ubuntu"
DATABASE_USER = "ubuntu"

DEBUG_USERS = [92664421553307648, 338486462519443461]  # usara, gegi


_log = logging.getLogger(__name__)


def setup_logging():
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


async def setup_codecs(con: Connection):
    await con.set_type_codec(
        "modlog_status_enum", encoder=lambda e: e.value, decoder=ModlogStatusEnum
    )

    await con.set_type_codec(
        "modlog_type_enum", encoder=lambda e: e.value, decoder=ModlogTypeEnum
    )


async def main():
    parser = argparse.ArgumentParser(prog="CazzuBot")
    parser.add_argument("-d", "--debug", action="store_true")
    debug = parser.parse_args().debug

    setup_logging()

    # Intents need to be set up to let discord know what we want for request
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    pw = getpass.getpass()

    # Codecs for enum conversion here

    async with asyncpg.create_pool(
        database=DATABASE_NAME,
        user=DATABASE_USER,
        host=DATABASE_HOST,
        password=pw,
        init=setup_codecs,
    ) as pool:
        async with CazzuBot(
            "d!",
            pool=pool,
            ext_path=EXTENSIONS_PATH,
            database=(DATABASE_NAME, DATABASE_HOST, DATABASE_USER),
            intents=intents,
            owner_id=OWNER_ID,
            debug=debug,
            debug_users=DEBUG_USERS,
        ) as bot:
            await bot.start(TOKEN)  # Ignore built-in logger


if __name__ == "__main__":
    asyncio.run(main())
