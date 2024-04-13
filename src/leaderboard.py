"""All functions related to making a leaderboard string from a database query.

Making a leadeboard is process.
    1. Get query from database; query should already be ranked and ordered.
    2. Call create_data_subset(); focus_index is the index of a row to "center" on.
    3. If you need to perform an operation across a column...
        3a. Transpose the window with zip(*window) to make data column-major.
            ---> Zipping arrays will yield its transpose; default is row-major
        3b. Do operations over columns.
        3c. Transpose back with zip e.g. zip(col1, col2, col3). Type-cast to list.
    4. Call generate(). Pass the window (entries), header, desired padding, etc.
    5. If needed, highlight a specifc index. If you wanted to highlight the focus from
       window, remember that create_window returns that index.
    6. The leaerboard now needs to be joined with newline to create full message.

With the complexity of a leaderboard, it would be wise to create a leaderboard class,
and delegate functionality to said class.
"""

import discord
from asyncpg import Record
from discord.ext import commands

from src import db, levels_helper, utility


def create_focus_subset(
    rows: list, focus_index: int, *, size: int = 5
) -> tuple[list, int]:
    """Create a sub-list of a bigger list, creating a window with a certain size.

    If the focus index is on edges, will still return the correct size.

    Also returns the 'corrected focus' as the second value.
    """
    if len(rows) <= size:
        return rows, focus_index

    extends = (size - 1) // 2  # 2
    lower = focus_index - extends  # -2
    upper = focus_index + extends  # 2

    # edge cases, focus index is "centered" on edge of rows
    if lower < 0:  # move window up
        upper -= lower
        lower = 0

    elif upper > len(rows) - 1:  # move window down
        lower -= upper - (len(rows) - 1)
        upper = len(rows) - 1

    window = rows[lower : upper + 1]
    corrected_index = focus_index - lower

    return window, corrected_index


def format(
    entries: list[list],
    headers: list,
    *,
    align: list,
    fill: str = ".",
    spacing: int = 2,
    max_padding: list = [],
) -> list[list[str], list[int]]:
    """Format row-major data as a text scoreboard.

    Returned is a list of strings, whose first element is the column names, and second
    element is a list of rows.

    entires: row-major data [row1[col1, col2, col3], row2[col1, col2, col3], ...]
    header: a list of the names of columns header[col1, col2, col3]
    align: a list of how to pad e.g. <, ^, >
    fill: character used for filling
    spacing: always put fill (if applicable) padding between columns
    max_padding: the max padding a column can have, if 0, "infinite" for that col
    """
    padding = calc_max_col_width(entries, headers, max_padding)

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
                    comma="" if isinstance(entries[row][col], str) else ",",  # else int
                )
            )
        rows_s.append(f"{(' ' if row % 2 else fill) * spacing}".join(row_raw))

    return [headers_s, *rows_s]


def highlight_row(
    scoreboard: list[str],
    index: int,
    column_widths: list[int],
    *,
    has_header: bool = True,
):
    """Modify IN PLACE the leaderboard to prepend an @ on indexed row.

    We do some disgusting string splicing. In order for this to work consistently, there
    needs to be some minmal padding. We will move column 1 of index to the right by
    1, and to do that, we need a little bit of padding so we don't cross over into
    column 2.
    """
    col1_width = column_widths[0]
    this_rank = scoreboard[index + int(has_header)][0:col1_width]
    scoreboard[index + 1] = (
        "@" + this_rank + scoreboard[index + int(has_header)][col1_width + 1 :]
    )
    return scoreboard


def calc_max_col_width(
    entries: list[list], headers: list[str] = None, max_padding: list[int] = None
) -> list[int]:
    """Return the max length of strings per column.

    Also takes into account commas in large numbers and a header if given.

    entires is [row1[col1, col2], ...]
    """
    max_padding = [x if x else 999 for x in max_padding]
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


async def prepare_leaderboard_subset(
    rows: list[Record],
    page: int,
) -> list[Record]:
    page = min(len(rows) // 10, page)
    if rows:
        width = 10
        lo = (page - 1) * width
        up = page * width
        subset = rows[lo:up]
        # embed = await self._format_leaderboard_subset(ctx, subset, uid=ctx.author.id)
    else:
        subset = None
        # embed.description = "There are no experience logs at this time."

    return subset


async def _format_leaderboard_subset(
    ctx: commands.Context,
    subset: list[Record],
    mode: db.table.WindowEnum = db.table.WindowEnum.SEASONAL,
    *,
    uid: int = None,
) -> discord.Embed:
    """Prepare the leaderboard for lazy computing when a page is requested.

    data: the raw result from query, containing (rank, uid, exp) in that order
    user: provide user if you want to highlight them, if exist
    """
    # Transpose for per-column transformations
    ranks, uids, exps = zip(*subset)
    lvls = [levels_helper.level_from_exp(e) for e in exps]
    names = [await utility.find_username(ctx.bot, ctx, id) for id in uids]

    # Transpose back to prepare to generate
    window = list(zip(ranks, exps, lvls, names))

    # Generate leaderboard
    headers = ["Rank", "Exp", "Lv", "User"]
    align = ["<", ">", ">", ">"]
    max_padding = [0, 0, 0, 16]

    raw_scoreboard = format(
        window,
        headers,
        align=align,
        max_padding=max_padding,
    )

    if uid in uids:
        col_widths = calc_max_col_width(window, headers, max_padding)
        subset_i = uids.index(uid)
        highlight_row(raw_scoreboard, subset_i, col_widths)

    scoreboard_s = "\n".join(raw_scoreboard)  # Final step to join.

    # Generate Embed
    embed = discord.Embed()

    embed.description = f"```py\n{scoreboard_s}```"

    embed.color = discord.Color.from_str("#a2dcf7")

    return embed
