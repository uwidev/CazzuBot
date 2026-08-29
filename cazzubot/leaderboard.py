"""Text leaderboard rendering (port of v1's ``src/leaderboard.py``).

Depended on by: ``plugins.experience`` (``exp top``) and ``plugins.frogs``
(frog board).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cazzubot import utils

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot


def format(
    entries: Sequence[Sequence[str | int]],
    headers: list[str],
    *,
    align: list[str],
    fill: str = ".",
    spacing: int = 2,
    max_padding: list[int] | None = None,
    highlight: int | None = None,
) -> list[str]:
    """Render row-major data as a text scoreboard (header first, then rows).

    ``highlight`` marks the indexed row with ``@`` in its first column (see
    :func:`highlight_row`) in the same pass — no need to re-derive column
    widths at the call site.
    """
    lines, widths = _format(
        entries,
        headers,
        align=align,
        fill=fill,
        spacing=spacing,
        max_padding=max_padding,
    )
    if highlight is not None:
        highlight_row(lines, highlight, widths)
    return lines


def _format(
    entries: Sequence[Sequence[str | int]],
    headers: list[str],
    *,
    align: list[str],
    fill: str = ".",
    spacing: int = 2,
    max_padding: list[int] | None = None,
) -> tuple[list[str], list[int]]:
    """Like ``format``, but also returns the per-column widths (one pass)."""
    padding = calc_max_col_width(entries, headers, max_padding)

    header_s = f"{' ' * spacing}".join(
        f"{headers[i]:{align[i]}{padding[i]}}" for i in range(len(padding))
    )

    rows_s: list[str] = []
    for row_i, row in enumerate(entries):
        row_fill = "" if row_i % 2 else fill
        row_s = f"{row_fill * spacing}".join(
            (
                f"{val:{row_fill}{align[col]}{padding[col]}{'' if isinstance(val, str) else ','}}"
                for col, val in enumerate(row)
            )
        )
        rows_s.append(row_s)

    return [header_s, *rows_s], padding


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


_NO_CAP = 999


def calc_max_col_width(
    entries: Sequence[Sequence[str | int]],
    headers: list[str] | None = None,
    max_padding: list[int] | None = None,
) -> list[int]:
    """Per-column max rendered width (commas for ints, header respected).

    ``max_padding`` caps each column; 0 means "no cap" (historical
    sentinel). A list shorter than the column count is padded with no-cap.
    """
    headers = headers or [""] * len(entries[0])
    caps = [_NO_CAP if x in (0, None) else x for x in (max_padding or [])]
    if len(caps) < len(headers):
        caps.extend([_NO_CAP] * (len(headers) - len(caps)))

    padding: list[int] = []
    for col in range(len(entries[0])):
        entire_col: list[str] = []
        for row in range(len(entries)):
            cell = entries[row][col]
            entire_col.append(
                str(cell) if isinstance(cell, str) else f"{cell:,}"
            )
        widest_val = len(sorted(entire_col, key=len)[-1])
        width = min(max(widest_val, len(headers[col])), caps[col])
        padding.append(width)
    return padding


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


async def resolve_names(bot: "CazzuBot", uids: Sequence[int]) -> list[str]:
    """Display names for uids, in order (raw id when unknown/partial)."""
    names: list[str] = []
    for uid in uids:
        found = await utils.find_user(bot, uid)
        names.append(utils.found_name(found, uid))
    return names


@dataclass(frozen=True, slots=True)
class FocusBoard:
    """The highlighted personal scoreboard around one member's row."""

    text: str
    subset: list[tuple[int, int, int]]
    subset_i: int
    rank: int
    value: int
    level: int | None = None


async def focus_board(
    bot: "CazzuBot",
    rows: Sequence[tuple[int, int, int]],
    focus_uid: int,
    *,
    headers: list[str],
    align: list[str],
    max_padding: list[int],
    level_of: Callable[[int], int] | None = None,
) -> FocusBoard | None:
    """The highlighted scoreboard around ``focus_uid``'s row; None when absent.

    Shared by the exp and frogs personal cards: focus-subset the ranked
    rows, resolve names, render with :func:`format` (highlighting the
    focus row) and expose the focus row's rank/value(/level) for the
    surrounding stats. ``level_of`` renders an extra Level column (exp
    cards); frogs' count card passes none.
    """
    uids = [r[1] for r in rows]
    if focus_uid not in uids:
        return None
    subset, subset_i = create_focus_subset(
        list(rows), uids.index(focus_uid)
    )
    ranks = [r[0] for r in subset]
    values = [r[2] for r in subset]
    lvls = [level_of(v) for v in values] if level_of else None
    names = await resolve_names(bot, [r[1] for r in subset])
    if lvls is not None:
        window = list(zip(ranks, values, lvls, names))
    else:
        window = list(zip(ranks, values, names))
    text = "\n".join(
        format(
            window,
            headers,
            align=align,
            max_padding=max_padding,
            highlight=subset_i,
        )
    )
    return FocusBoard(
        text=text,
        subset=subset,
        subset_i=subset_i,
        rank=ranks[subset_i],
        value=values[subset_i],
        level=lvls[subset_i] if lvls else None,
    )
