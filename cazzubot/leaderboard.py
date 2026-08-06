"""Text leaderboard rendering (port of v1's ``src/leaderboard.py``)."""

from collections.abc import Sequence
from typing import Any

import discord

from cazzubot import levels


def create_focus_subset(
    rows: list[Any], focus_index: int, *, size: int = 5
) -> tuple[list[Any], int]:
    """Sliding window of ``size`` centered on ``focus_index``.

    Edge-corrected; returns (window, corrected_focus_index).
    """
    if len(rows) <= size:
        return rows, focus_index

    extends = (size - 1) // 2
    lower = focus_index - extends
    upper = focus_index + extends

    if lower < 0:
        upper -= lower
        lower = 0
    elif upper > len(rows) - 1:
        lower -= upper - (len(rows) - 1)
        upper = len(rows) - 1

    window = rows[lower : upper + 1]
    return window, focus_index - lower


def calc_max_col_width(
    entries: Sequence[Sequence[str | int]],
    headers: list[str] | None = None,
    max_padding: list[int] | None = None,
) -> list[int]:
    """Per-column max rendered width (commas for ints, header respected)."""
    headers = headers or [""] * len(entries[0])
    max_padding = [x if x else 999 for x in (max_padding or [])]
    if not max_padding:
        max_padding = [999] * len(headers)

    padding: list[int] = []
    for col in range(len(entries[0])):
        entire_col: list[str] = []
        for row in range(len(entries)):
            cell = entries[row][col]
            entire_col.append(
                str(cell) if isinstance(cell, str) else f"{cell:,}"
            )
        widest_val = len(sorted(entire_col, key=len)[-1])
        width = min(max(widest_val, len(headers[col])), max_padding[col])
        padding.append(width)
    return padding


def format(
    entries: Sequence[Sequence[str | int]],
    headers: list[str],
    *,
    align: list[str],
    fill: str = ".",
    spacing: int = 2,
    max_padding: list[int] | None = None,
) -> list[str]:
    """Render row-major data as a text scoreboard (header first, then rows)."""
    padding = calc_max_col_width(entries, headers, max_padding)

    header_s = f"{' ' * spacing}".join(
        f"{headers[i]:{align[i]}{padding[i]}}" for i in range(len(padding))
    )

    rows_s: list[str] = []
    for row_i, row in enumerate(entries):
        row_fill = "" if row_i % 2 else fill
        row_s = f"{(' ' if row_i % 2 else fill) * spacing}".join(
            (
                f"{val:{row_fill}{align[col]}{padding[col]}{'' if isinstance(val, str) else ','}}"
                for col, val in enumerate(row)
            )
        )
        rows_s.append(row_s)

    return [header_s, *rows_s]


def highlight_row(
    scoreboard: list[str],
    index: int,
    column_widths: list[int],
    *,
    has_header: bool = True,
) -> list[str]:
    """Prepend ``@`` to the rank column of the indexed row (in place)."""
    row_i = index + int(has_header)
    col1_width = column_widths[0]
    this_rank = scoreboard[row_i][0:col1_width]
    scoreboard[row_i] = (
        "@" + this_rank + scoreboard[row_i][col1_width + 1 :]
    )
    return scoreboard


async def format_leaderboard_embed(
    rows: Sequence[tuple[int, int, int]],
    names: Sequence[str],
    *,
    uid: int | None = None,
) -> discord.Embed:
    """Render ``(rank, uid, exp)`` rows into the standard leaderboard embed.

    Columns: Rank / Exp / Lv / User. ``names`` must be user-resolved display
    names in the same order. Highlights the user's row with ``@``.
    """
    ranks = [r[0] for r in rows]
    uids = [r[1] for r in rows]
    exps = [r[2] for r in rows]
    lvls = [levels.level_from_exp(e) for e in exps]

    window = list(zip(ranks, exps, lvls, names))
    headers = ["Rank", "Exp", "Lv", "User"]
    align = ["<", ">", ">", ">"]
    max_padding = [0, 0, 0, 16]

    scoreboard = format(
        window, headers, align=align, max_padding=max_padding
    )

    if uid is not None and uid in uids:
        col_widths = calc_max_col_width(window, headers, max_padding)
        highlight_row(scoreboard, uids.index(uid), col_widths)

    embed = discord.Embed(
        description=f"```py\n{chr(10).join(scoreboard)}```",
        color=discord.Color.from_str("#a2dcf7"),
    )
    return embed
