"""Shared plumbing for the admin CLI: REST client boot, dispatch, helpers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import hikari
import pendulum

from cazzubot.config import Config

# roles-specific default (channels declares its own CHANNELS_BACKUP_DIR)
DEFAULT_ROLES_BACKUP_DIR = Path("data/roles_backups")

# live command handler: (rest client, config, parsed args) -> exit code
LiveHandler: TypeAlias = Callable[
    [hikari.api.RESTClient, Config, argparse.Namespace], Awaitable[int]
]

# Presets derived when exporting the manifest from the live guild's state.
# Guild-specific by nature (preset "mod" names a live role in Club Cirno);
# keep in sync when that guild's roles change. Used by both `roles export`
# and the offline `manifest render`.
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
    verb. The framework itself only adds ``--bot``/``--guild``.
    """

    name: str
    help: str
    commands: dict[str, Command]
    common_args: tuple[Callable[[argparse.ArgumentParser], None], ...] = ()


async def with_client(
    handler: LiveHandler,
    args: argparse.Namespace,
) -> int:
    """Boot a throwaway REST client, run ``handler``, close.

    Live commands go through here so the CLI works even while the bot is
    offline. hikari's REST client needs an explicit ``"Bot"`` token type
    (its acquire default is BEARER).
    """
    config = Config.load(bot=args.bot, guild=args.guild)
    app = hikari.RESTApp()
    await app.start()
    try:
        async with app.acquire(config.token, "Bot") as client:
            try:
                return await handler(client, config, args)
            except Exception as err:
                print(f"error: {err}", file=sys.stderr)
                return 1
    finally:
        await app.close()


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


async def require_guild(
    client: hikari.api.RESTClient, config: Config
) -> hikari.Guild | None:
    """The configured guild, or None after printing an error."""
    try:
        return await client.fetch_guild(config.guild_id)
    except hikari.NotFoundError:
        print(
            f"error: guild {config.guild_id} not found",
            file=sys.stderr,
        )
        return None


def export_stamp() -> str:
    """Human-readable UTC timestamp for the manifest header."""
    return f"{pendulum.now('UTC').format('YYYY-MM-DD HH:mm:ss')} UTC"
