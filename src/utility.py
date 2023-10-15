"""General-purpose functions."""
import asyncio
import logging

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


def max_width(entries: list[list], headers: list[str] = []) -> list[int]:
    """Return the max length of strings per column.

    Also takes into account commas in large numbers and a header if given.

    entires is [row1[col1, col2], ...]
    """
    padding = []
    for col in range(len(entries[0])):
        if isinstance(entries[0][col], str):
            entire_col = list(entries[row][col] for row in range(len(entries)))
        else:  # is a number, take into account comma
            entire_col = list(f"{entries[row][col]:,}" for row in range(len(entries)))
        widest_col = len(sorted(entire_col, key=len)[-1])
        padding.append(max(widest_col, len(headers[col])))

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
    align=list,
    fill: str = ".",
    min_padding: int = 2,
) -> list[list[str], list[int]]:
    """Format and return a text-based scoreboard with dynamic alignment.

    Returned is a list of strings. You will need to join with newline.
    Also returns calculated padding for any further transformation.

    rows: the format of [row1[col1, col2, col3], row2[col1, col2, col3], ...]
    header: a list of the names of columns header[col1, col2, col3]
    align: a list of how to pad e.g. <, ^, >
    fill: character used for filling
    min_padding: always put fill (if applicable) padding between columns

    """
    padding = max_width(entries, headers)

    header_format = "{val:{align}{pad}}"
    headers_s = f"{' ' * min_padding}".join(
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
        rows_s.append(f"{(' ' if row % 2 else fill) * min_padding}".join(row_raw))

    return [headers_s, *rows_s], padding


def focus_list(rows: list, focus_index: int, size: int = 5):
    """Create a sub-list of a bigger list, creating a window with a certain size.

    If the focus index is on edges, will still return the correct size.

    Also returns the 'corrected focus' as the second value.
    """
    # if size >= len(rows):

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
