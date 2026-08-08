"""Shared plumbing for the admin CLI: client boot, dispatch types, helpers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import discord
import pendulum

from cazzubot.config import Config

DEFAULT_BACKUP_DIR = Path("data/roles_backups")

# live command handler: (client, config, parsed args) -> exit code
LiveHandler: TypeAlias = Callable[
    [discord.Client, Config, argparse.Namespace], Awaitable[int]
]

# Presets derived when exporting the manifest from this guild's live state
# (used by both `roles export` and the offline `manifest render`).
EXPORT_PRESETS = {"member": "@everyone", "mod": "👀 | Mod Baka"}


@dataclass(frozen=True, slots=True)
class Command:
    """One verb of a domain: the handler plus how to expose it.

    Live handlers take ``(client, config, args)``; offline handlers take
    ``(args)``. Both are async and return the process exit code.
    """

    handler: Callable[..., Awaitable[int]]
    live: bool = True
    help: str = ""
    add_args: Callable[[argparse.ArgumentParser], None] | None = None


@dataclass(frozen=True, slots=True)
class Domain:
    """A CLI domain (roles, snapshot, manifest, …): verbs under one name.

    ``common_args`` holds flag-group callables applied to a shared parent
    parser that every verb inherits via argparse ``parents=`` — the way to
    give a whole domain a flag (e.g. ``--file``) without repeating it per
    verb. The framework itself only adds ``--production``.
    """

    name: str
    help: str
    commands: dict[str, Command]
    common_args: tuple[Callable[[argparse.ArgumentParser], None], ...] = ()


async def with_client(
    handler: LiveHandler,
    args: argparse.Namespace,
) -> int:
    """Boot a throwaway discord connection, run ``handler`` on ready, close.

    Live commands go through here so the CLI works even while the bot is
    offline. The connection is closed before this function returns.
    """
    config = Config.load(production=args.production)
    intents = discord.Intents.default()
    intents.members = True
    client = discord.Client(intents=intents)
    outcome = {"code": 2}

    @client.event
    async def on_ready() -> None:  # pyright: ignore[reportUnusedFunction]  # registered via @client.event
        try:
            outcome["code"] = await handler(client, config, args)
        except Exception as err:
            print(f"error: {err}", file=sys.stderr)
            outcome["code"] = 1
        await client.close()

    try:
        await client.start(config.token)
    except KeyboardInterrupt:
        await client.close()
    return outcome["code"]


def confirm(
    args: argparse.Namespace, *, prompt: str = "proceed? [y/N] "
) -> bool:
    """Honor ``--yes``; otherwise ask on a tty and default to no."""
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        return False
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")


def require_guild(
    client: discord.Client, config: Config
) -> discord.Guild | None:
    """The configured guild, or None after printing an error."""
    guild = client.get_guild(config.guild_id)
    if guild is None:
        print(
            f"error: guild {config.guild_id} not found",
            file=sys.stderr,
        )
    return guild


def export_stamp() -> str:
    """Human-readable UTC timestamp for the manifest header."""
    return f"{pendulum.now('UTC').format('YYYY-MM-DD HH:mm:ss')} UTC"
