"""General-purpose functions."""
import asyncio
import copy
import json
import logging
from collections.abc import Callable

import discord
import pendulum
from asyncpg import Record
from discord.ext import commands


_log = logging.getLogger("discord")
_log.setLevel(logging.INFO)


class ReadOnlyDict(dict):
    """Safeguard to prevent writing to DB templates."""

    def __setitem__(self, key, value):
        msg = "read-only dictionary, setting values is not supported"
        raise TypeError(msg)

    def __delitem__(self, key):
        msg = "read-only dict, deleting values is not supported"
        raise TypeError(msg)


def else_if_none(*args, raise_err=True):
    for arg in args:
        if arg:
            return arg

    if raise_err:
        msg = "No arguments passed resulted in a non-None value"
        raise ValueError(msg)

    return None


def max_width(
    entries: list[list], headers: list[str] = None, max_padding: list[int] = None
) -> list[int]:
    """Return the max length of strings per column.

    Also takes into account commas in large numbers and a header if given.

    entires is [row1[col1, col2], ...]
    """
    padding = []

    if not headers:
        headers = [""] * len(entries)

    if not max_padding:
        max_padding = [999] * len(headers)

    for col in range(len(entries[0])):
        if isinstance(entries[0][col], str):
            entire_col = list(entries[row][col] for row in range(len(entries)))
        else:  # is a number, take into account comma
            entire_col = list(f"{entries[row][col]:,}" for row in range(len(entries)))
        widest_val = len(sorted(entire_col, key=len)[-1])
        width = max(widest_val, len(headers[col]))
        width_trunc = min(width, max_padding[col])
        padding.append(width_trunc)

    return padding


def highlight_scoreboard(
    scoreboard: list[str],
    index: int,
    col1_padding: int,
    *,
    header: bool = True,
):
    """Modify the scoreboard to add an @ in front of the row on the text-scoreboard.

    We do some disgusting string splicing. In order for this to work consistently, there
    needs to be some minmal padding. We will move column 1 of index to the right by
    1, and to do that, we need a little bit of padding so we don't cross over into
    column 2.
    """
    this_rank = scoreboard[index + int(header)][0:col1_padding]
    scoreboard[index + 1] = (
        "@" + this_rank + scoreboard[index + int(header)][col1_padding + 1 :]
    )
    return scoreboard


def generate_scoreboard(
    entries: list,
    headers: list,
    align: list,
    *,
    fill: str = ".",
    spacing: int = 2,
    max_padding: list = [],
) -> list[list[str], list[int]]:
    """Format and return a text-based scoreboard with dynamic alignment.

    Returned is a list of strings. You will need to join with newline.
    Also returns calculated padding for any further transformation.

    rows: the format of [row1[col1, col2, col3], row2[col1, col2, col3], ...]
    header: a list of the names of columns header[col1, col2, col3]
    align: a list of how to pad e.g. <, ^, >
    fill: character used for filling
    spacing: always put fill (if applicable) padding between columns
    max_padding: the max padding a column can have, if 0, "infinite" for that col
    """
    max_padding = [x if x else 999 for x in max_padding]  # if pad 0, set 999
    padding = max_width(entries, headers, max_padding)

    header_format = "{val:{align}{pad}}"
    headers_s = f"{' ' * spacing}".join(
        header_format.format(val=headers[i], align=align[i], pad=padding[i])
        for i in range(len(padding))
    )

    rows_s = []
    form = "{val:{fill}{align}{pad}{comma}}"
    for row in range(len(entries)):
        row_raw = []
        for col in range(len(entries[row])):
            row_raw.append(
                form.format(
                    val=entries[row][col],
                    fill="" if row % 2 else fill,
                    align=align[col],
                    pad=padding[col],
                    comma="" if isinstance(entries[row][col], str) else ",",
                )
            )
        rows_s.append(f"{(' ' if row % 2 else fill) * spacing}".join(row_raw))

    return [headers_s, *rows_s], padding


def focus_list(rows: list, focus_index: int, size: int = 5):
    """Create a sub-list of a bigger list, creating a window with a certain size.

    If the focus index is on edges, will still return the correct size.

    Also returns the 'corrected focus' as the second value.
    """
    extends = (size - 1) // 2
    corrected_center = min(max(extends, focus_index), len(rows) - 1 - extends)

    if focus_index <= extends:  # focus too front
        corrected_focus = focus_index
    elif focus_index > len(rows) - 1 - extends:  # focus too end
        corrected_focus = focus_index - corrected_center
    else:  # just right
        corrected_focus = extends

    return (
        rows[corrected_center - extends : corrected_center + extends + 1],
        corrected_focus,
    )


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


valid_embed_structure = [
    "title",
    "type",
    "description",
    "url",
    "color",
    "timestamp",
    "thumbnail",
    "video",
    "provider",
    "author",
    "fields",
    "image",
    "footer",
]


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


def verify_embed_structure(embed_dict: dict):
    """Check to see if embed dict only has attributes related to embed."""


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


def calc_min_rank(rank_thresholds: list[Record], level) -> tuple[int, int]:
    """Naively determine rank based on level from list of records.

    Returns the rank id, and the index at which the rank is.
    """
    if level < rank_thresholds[0]["threshold"]:
        return None, None

    for i in range(1, len(rank_thresholds)):
        if level < rank_thresholds[i]["threshold"]:
            return rank_thresholds[i - 1]["rid"], i - 1

    return rank_thresholds[-1]["rid"], len(rank_thresholds) - 1


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


def fix_timestamps_iterable(embed: dict):
    """Convert key timestamp to isoformat for database."""
    timestamp = embed.get("timestamp", None)
    if timestamp:
        embed["timestamp"] = pendulum.parser.parse(timestamp).isoformat()


def prepare_message(decoded: dict) -> tuple[str, dict, list]:
    """Parse dictionary to embed objects, return as tuple for sending message."""
    content = decoded.get("content", None)
    embed = embed_from_decoding(decoded)
    embeds = embeds_from_decoding(decoded)

    return content, embed, embeds


def embeds_from_decoding(d: dict):
    """Return a list of embed objects from a json.

    None if empty.
    """
    embeds = d.get("embeds", None)
    if not embeds:
        return None

    return [discord.Embed.from_dict(embed) for embed in embeds]


def embed_from_decoding(d: dict):
    """Return an embed object from json.

    None if doesn't exist.
    """
    embed = d.get("embed", None)
    if not embed:
        return None

    return discord.Embed.from_dict(embed)


def deep_map(d: dict, formatter: Callable, **kwarg: dict):
    """Walk the iterable and applies calls formatter to all strings.

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


async def verify_json(
    bot,
    ctx,
    message: str,
    formatter: Callable = None,
    **kwarg,
):
    """Verify if a user's provided json argument is valid.

    Return its decoded dict if valid, None if not.

    If formatter is given, it will call that formatter and pass all kwargs to it. This
    formatter will be called on all str objects in the json. The returned dict is
    the pre-formatted version.
    """
    decoded = None
    try:
        decoded: dict = bot.json_decoder.decode(message)  # decode to verify valid json

        fix_timestamps_iterable(decoded)

        # send embed to verify valid embed
        demo = copy.deepcopy(decoded)

        if formatter:
            deep_map(demo, formatter, **kwarg)

        content, embed, embeds = prepare_message(demo)

        await ctx.reply(
            content=content,
            embed=embed,
            embeds=embeds,
        )

    except json.decoder.JSONDecodeError as err:
        msg = "Embed is not valid JSON object"
        raise commands.BadArgument(msg) from err

    except discord.errors.HTTPException as err:
        msg = "Embed is not a valid embed object"
        raise commands.BadArgument(msg) from err

    else:
        return decoded
