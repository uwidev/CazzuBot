"""Runs the bot.

Bot grabs API key from secret/setup.py.

Docker sets fresh database password from secret/db
"""

import argparse
import asyncio
import logging
import os
import time

import aiofiles
import asyncpg
import discord
import pendulum
from asyncpg import Connection
from discord.utils import _ColourFormatter, stream_supports_colour

from src.cazzubot import CazzuBot
from src.db.table import (
    FrogTypeEnum,
    MemberExpLogSourceEnum,
    ModlogStatusEnum,
    ModlogTypeEnum,
    WelcomeModeEnum,
    WindowEnum,
)
from src.json_handler import dumps, loads


EXTENSIONS_PATH = r"ext"

DEBUG_USERS = [92664421553307648, 338486462519443461]  # usara, gegi


_log = logging.getLogger(__name__)


def setup_logging(log_path: str, *, debug: bool = False):
    """Write info logging to console and debug logging to file."""

    def timetz(*args):
        return pendulum.now(tz="UTC").timetuple()

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)

    file_hanndler = logging.FileHandler(
        filename=f"{log_path}/discord.log", encoding="utf-8", mode="w+"
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

    await con.set_type_codec(
        "window_enum", encoder=lambda e: e.value, decoder=WindowEnum
    )

    await con.set_type_codec(
        "frog_type_enum", encoder=lambda e: e.value, decoder=FrogTypeEnum
    )

    await con.set_type_codec(
        "member_exp_log_source_enum",
        encoder=lambda e: e.value,
        decoder=MemberExpLogSourceEnum,
    )

    await con.set_type_codec(
        "welcome_mode_enum",
        encoder=lambda e: e.value,
        decoder=WelcomeModeEnum,
    )

    await con.set_type_codec("json", encoder=dumps, decoder=loads, schema="pg_catalog")

    await con.set_type_codec("jsonb", encoder=dumps, decoder=loads, schema="pg_catalog")


async def main():
    # Environment parsing
    parser = argparse.ArgumentParser(prog="CazzuBot")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("-p", "--production", action="store_true")
    parser.add_argument("-s", "--sandbox", action="store_true")
    debug = parser.parse_args().debug
    production = parser.parse_args().production
    sandbox = parser.parse_args().sandbox

    postgres_db = os.getenv("POSTGRES_DB")
    postgres_user = os.getenv("POSTGRES_USER")
    postgres_password_file = os.getenv("POSTGRES_PASSWORD_FILE")
    postgres_ip = os.getenv("POSTGRES_IP")
    postgres_port = os.getenv("POSTGRES_PORT")
    token_file = os.getenv("TOKEN_FILE")
    owner_id = int(os.getenv("OWNER_ID"))
    log_path = os.getenv("LOG_PATH")

    # For development purposes
    postgres_ip_dev = os.getenv("POSTGRES_IP_DEV")
    token_file_dev = os.getenv("TOKEN_FILE_DEV")

    # Read secret files
    async with aiofiles.open(postgres_password_file, mode="r") as file:
        pw = await file.readline()

    async with aiofiles.open(token_file, mode="r") as file:
        token = await file.readline()

    async with aiofiles.open(token_file_dev, mode="r") as file:
        token_dev = await file.readline()

    setup_logging(log_path, debug=debug)

    if debug:
        _log.info("RUNNNING IN DEBUG MODE")

    mode = "PRODUCTION" if production else "DEVELOP"
    _log.info(f"Bot running in {mode} mode")

    prefix = "c!" if production else "d!"
    _log.info(f"Prefix is set to: {prefix}")

    if sandbox:
        _log.warning("RUNNING IN SANDBOX MODE")

    # Bot setup and run
    # Intents need to be set up to let discord know what we want for request
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    async with asyncpg.create_pool(
        database=postgres_db,
        user=postgres_user,
        host=postgres_ip if production else postgres_ip_dev,
        port=postgres_port,
        password=pw,
        init=setup_codecs,
    ) as pool:
        async with CazzuBot(
            prefix,
            pool=pool,
            ext_path=EXTENSIONS_PATH,
            intents=intents,
            owner_id=owner_id,
            debug=debug,
            debug_users=DEBUG_USERS,
            sandbox=sandbox,
        ) as bot:
            await bot.start(
                token if production else token_dev
            )  # Ignore built-in logger


if __name__ == "__main__":
    os.system("cls" if os.name == "nt" else "clear")
    asyncio.run(main())
