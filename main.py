#!/bin/env python
"""Run the bot.

Usage: CazzuBot [-h] [-d] [-p] [-s]

Options:
  -d, --debug       Run in debug mode; only owner/debug users may run commands
  -p, --production  Run with the production token
  -s, --sandbox     Load only the sandbox plugins (poll, board, dev)
"""

import argparse
import logging
import os
import subprocess
from pathlib import Path

from typing_extensions import override

from cazzubot import CazzuBot, Config

_log = logging.getLogger(__name__)


class _ColourFormatter(logging.Formatter):
    """ANSI-coloured console formatter (replaces discord.py's internal one)."""

    _colours = {
        logging.DEBUG: "\x1b[38;5;250m",
        logging.INFO: "\x1b[38;5;39m",
        logging.WARNING: "\x1b[38;5;220m",
        logging.ERROR: "\x1b[38;5;196m",
        logging.CRITICAL: "\x1b[31m",
    }

    @override
    def format(self, record: logging.LogRecord) -> str:
        colour = self._colours.get(record.levelno, "")
        record.levelname = f"{colour}{record.levelname:<8}\x1b[0m"
        return super().format(record)


def main() -> None:
    parser = argparse.ArgumentParser(prog="CazzuBot")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("-p", "--production", action="store_true")
    parser.add_argument("-s", "--sandbox", action="store_true")
    args = parser.parse_args()

    config = Config.load(
        debug=args.debug,
        production=args.production,
        sandbox=args.sandbox,
    )

    setup_logging("log", debug=config.debug)

    _log.info(
        "running in %s mode",
        "SANDBOX"
        if config.sandbox
        else ("PRODUCTION" if args.production else "DEVELOP"),
    )
    _log.info("guild_id=%s", config.guild_id)

    bot = CazzuBot(config)
    bot.run()


def setup_logging(log_dir: str | Path, *, debug: bool = False) -> None:
    """Write INFO to console and DEBUG to a rotating-ish log file."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # aiosqlite logs every statement at DEBUG — bury it or the console
    # becomes unreadable in -d mode
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if debug else logging.INFO)

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(
        filename=f"{log_dir}/discord.log", encoding="utf-8", mode="w+"
    )
    file_handler.setLevel(logging.DEBUG)

    fmt = "[{asctime}] [{levelname:<8}] {name}: {message}"
    formatters = {
        "file": logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S", style="{"),
        "console": (
            _ColourFormatter(fmt, "%Y-%m-%d %H:%M:%S", style="{")
            if console.stream.isatty()
            else logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S", style="{")
        ),
    }
    for handler in (console, file_handler):
        handler.setFormatter(
            formatters[
                "file"
                if isinstance(handler, logging.FileHandler)
                else "console"
            ]
        )
        logger.addHandler(handler)


if __name__ == "__main__":
    subprocess.run("cls" if os.name == "nt" else "clear", shell=True)
    main()
