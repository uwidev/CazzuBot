"""General-purpose functions."""

import asyncio
import copy
import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

import discord
import pendulum
from asyncpg import Record
from discord.ext import commands

from main import CazzuBot
from src.ntlp import (
    InvalidTimeError,
    normalize_time_str,
)


_log = logging.getLogger("discord")
_log.setLevel(logging.INFO)


class OldNew(NamedTuple):
    """Just a packer for old and new."""

    old: int
    new: int


class ReadOnlyDict(dict):
    """Safeguard to prevent writing to DB templates."""

    def __setitem__(self, key, value):
        msg = "read-only dictionary, setting values is not supported"
        raise TypeError(msg)

    def __delitem__(self, key):
        msg = "read-only dict, deleting values is not supported"
        raise TypeError(msg)


def else_if_none(*args, raise_err=True):
    """Return the first argument evaluated to be not null.

    Somewhat bad practice. It will evaluate EVERYTHING passed into it, meaning that if
    there's an API call, or anything blocking, it will always stall on that evaluation.

    Suggested not to use anymore and phase out for manual code control... or something
    better.

    An alternative would be to pack input as [(function, *arg, **kwarg)], loop and call.
    """
    for arg in args:
        if arg is not None:
            return arg

    if raise_err:
        msg = "No arguments passed resulted in a non-None value"
        raise ValueError(msg)

    return None


def binary_search(arr, target):
    """Return the index of target in arr, None if not found."""
    left, right = 0, len(arr) - 1

    while left <= right:
        mid = left + (right - left) // 2

        if target == arr[mid]:
            return mid

        if target <= arr[mid]:
            right = mid - 1
        else:
            left = mid + 1

    return None


def get_key_structure(d: dict):
    """Return all keys for a dict while retaining it's nested structure."""
    keys = []
    for k, v in d.items():
        keys.append(k)
        if isinstance(v, dict):
            keys.append(
                get_key_structure(v)
            )  # Recursively get keys for nested dictionaries
    return keys


def is_subset_r(sub, main):
    """Compare two iterables and recursively checks if sub is a subset of main."""
    for item in sub:
        try:
            iter(item)
            if not any(is_subset_r(item, m) for m in main):
                return False
        except TypeError:
            if item not in main:
                return False

        return True
    return None


def author_confirm(
    confirmation_msg: str = "Please confirm.", delete_after: bool = True
):
    """Force author to confirm that they want to run the command.

    Meant to be used as a decorator like so:

    @author_confirm(**kwargs)
    @command.command()
    async def command(ctx):
        ...
    """

    async def confirm(ctx: commands.Context) -> bool:
        # When help is invoked, it walks through checks on all commands. We don't want
        # trigger confirmation request when querying for help.
        if ctx.invoked_with == "help":
            return True

        author = ctx.author
        confirmation = await ctx.send(confirmation_msg)
        await confirmation.add_reaction("❌")
        await confirmation.add_reaction("✅")

        def check(reaction, user):
            if user.id == author.id and reaction.message.id == confirmation.id:
                if reaction.emoji in ["❌", "✅"]:
                    return True

            return False

        try:
            reaction, _ = await ctx.bot.wait_for("reaction_add", check=check, timeout=7)
        except asyncio.TimeoutError:
            if delete_after:
                await confirmation.delete()
            return False

        if reaction.emoji == "❌":
            if delete_after:
                await confirmation.delete()
            return False

        if delete_after:
            await confirmation.delete()

        return True

    return commands.check(confirm)


def update_dict(old: dict, ref: dict) -> dict:
    """Return a new dict that matches reference dict, retaining values recursively.

    Does NOT remap fields, and is something that might need to be implemented
    in the future when making restructuring existing fields.

    Example:
    -------
        Input
        old = {'a': 3, 'b': {'x': 5}, 'c': 7}
        ref = {'a': 0, 'b': {'y': 0}, 'd': 2}

    Returns:
    -------
        {'a': 3, 'b': {'y': 0}, 'd': 2}

    """
    new = {}

    common_fields = set(old.keys()).intersection(ref.keys())
    for field in common_fields:
        if isinstance(old[field], dict):
            new[field] = update_dict(old[field], ref[field])
        else:
            new[field] = old[field]

    new_fields = set(ref.keys()).difference(common_fields)
    for field in new_fields:
        new[field] = ref[field]

    return new


def deep_map(d: dict, formatter: Callable, **kwarg: dict):
    """Walk the iterable IN PLACE and applies calls formatter to all strings.

    The formatter function should take s as an positional argument, and require keyword
    arguments for anything else it needs.

    e.g.
    def _formatter(s: str, *, member)

    Having the * tells python to consume all positional arguments, and following
    arguments must be explicitly writted as keyword arguments.

    When calling utility.verify_json, keyword arguments should match the formatter.
    """

    def walk_iterable(itr):
        for i in range(len(itr)):
            if isinstance(itr[i], dict):
                walk_dict(itr[i])

            elif isinstance(itr[i], str):
                itr[i] = formatter(itr[i], **kwarg)

            elif isinstance(itr[i], list | set):
                walk_iterable(itr[i])

    def walk_dict(d):
        for k in d:
            if isinstance(d[k], dict):
                walk_dict(d[k])

            elif isinstance(d[k], str):
                d[k] = formatter(d[k], **kwarg)

            elif isinstance(d[k], list | set):
                walk_iterable(d[k])

    walk_dict(d)


def ordinal(n: int) -> str:
    """Return the number with it's original suffix as a string.

    Source: https://leancrew.com/all-this/2020/06/ordinals-in-python/
    """
    s = ("th", "st", "nd", "rd") + ("th",) * 10
    v = n % 100
    if v > 13:  # noqa: PLR2004
        return f"{n}{s[v%10]}"

    return f"{n}{s[v]}"


def prase_dur_str_mix(self, raw) -> tuple[pendulum.DateTime, str]:
    """Transform a time string mix.

    Time is optional, and must come first.

    ==== Examples of expected output =====
    DateTime dur 2h, "foo bar barz"         "2h foo bar barz"
    None, "foo bar barz"                    "2h foo bar barz"
    None, "foo 2h bar barz"                 "foo 2h bar barz"
    """
    time = None
    s = raw
    if raw:
        if raw.find(" ") != -1:
            dur_raw, s = raw.split(" ", 1)
        else:
            dur_raw = raw
        try:
            time = normalize_time_str(dur_raw)
        except InvalidTimeError:
            s = raw

    return time, s


def calc_percentile(rank: int, total: int) -> float:
    return (total - rank + 1) / (total) * 100.0


async def find_username(bot: CazzuBot, ctx: commands.Context, uid: int) -> str:
    """Attempt to resolve a user id to a member's display name.

    If fails, return uid.
    """
    res = await find_user(bot, ctx, uid)
    return res.display_name if hasattr(res, "display_name") else res


async def find_user(bot: CazzuBot, ctx: commands.Context, uid: int) -> discord.Member:
    """Attempt to find a user, looking at internal cache first, then fetching.

    If fails, return None.
    """
    res = ctx.guild.get_member(uid)

    if res is None:
        res = bot.get_user(uid)

    if res is None:
        _log.info(f"uid {uid} not found, fetching")
        res = await bot.fetch_user(uid)
        _log.info(f"maybe found? was {res}")

    return res


def prepare_embed(title: str, desc: str, color: bytes = 0x9EDBF7) -> discord.Embed:
    """Create a simple discord.embed object and returns it."""
    embed = discord.Embed(title=title, description=desc, color=0x9EDBF7)

    embed.set_footer(text="-sarono", icon_url="https://i.imgur.com/BAj8IWu.png")

    return embed
