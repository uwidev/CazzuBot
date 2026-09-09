"""Text leaderboard rendering (port of v1's ``src/leaderboard.py``).

Depended on by: ``plugins.experience`` (``exp top``) and ``plugins.frogs``
(frog board).
"""

import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core import ansi, utils

if TYPE_CHECKING:
    from core.bot import CazzuBot


def format(
    entries: Sequence[Sequence[str | int]],
    headers: list[str],
    *,
    align: list[str],
    fill: str = ".",
    spacing: int = 2,
    max_padding: list[int] | None = None,
    highlight: int | None = None,
    color: bool = False,
) -> list[str]:
    """Render row-major data as a text scoreboard (header first, then rows).

    ``highlight`` marks the indexed row with ``@`` in its first column (see
    :func:`highlight_row`) in the same pass — no need to re-derive column
    widths at the call site.

    ``color`` wraps every line in its ANSI color (see :func:`colorize`);
    the result only renders in an ```` ```ansi ```` code block.
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
    if color:
        colorize(lines, highlight)
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
        _pad(headers[i], padding[i], fill=" ", align=align[i])
        for i in range(len(padding))
    )

    rows_s: list[str] = []
    for row_i, row in enumerate(entries):
        # even rows carry the dotted "leader" fill, odd rows plain spaces;
        # the separator follows the same alternation (never empty, or the
        # columns would run together)
        row_fill = fill if row_i % 2 == 0 else " "
        separator = row_fill * spacing
        cells: list[str] = []
        for col, val in enumerate(row):
            text = val if isinstance(val, str) else f"{val:,}"
            cells.append(
                _pad(text, padding[col], fill=row_fill, align=align[col])
            )
        rows_s.append(separator.join(cells))

    return [header_s, *rows_s], padding


_ZERO_WIDTH = frozenset({"\u200b", "\u2060"})
_REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)
_ZWJ = "\u200d"
_EMOJI_PRESENTATION = "\ufe0f"


def display_width(text: str) -> int:
    """Rendered cell width of ``text`` inside a Discord code block.

    Discord renders code blocks monospaced, where East-Asian wide/fullwidth
    characters and emoji occupy two cells and combining marks and zero-width
    characters occupy none — so ``len`` undercounts exactly the names that
    would otherwise push a row out of alignment. A joined glyph counts once:
    a ZWJ sequence (👨‍👩‍👧) is one emoji, an emoji-presentation selector
    (❤️) widens its base, and a regional-indicator pair (🇯🇵) is one flag.
    ANSI color sequences are stripped first: they occupy no cells.
    Exotic sequences (skin-tone modifiers, keycaps) can still be off by a
    cell — close enough for a scoreboard.
    """
    width = 0
    last = 0  # width of the glyph counted last (for the VS16 upgrade)
    joined = False  # previous character was a ZWJ
    regional = False  # previous character was a lone regional indicator
    for char in ansi.strip(text):
        if char == _ZWJ:
            joined = True
            continue
        if char == _EMOJI_PRESENTATION:
            if last:
                width += 2 - last
                last = 2
            continue
        if char in _ZERO_WIDTH or unicodedata.combining(char):
            continue
        if joined:  # tail of a ZWJ sequence: same glyph
            joined = False
            continue
        if ord(char) in _REGIONAL_INDICATORS:
            if regional:  # a pair renders as one flag
                regional = False
                continue
            regional = True
            glyph = 2
        else:
            regional = False
            glyph = (
                2
                if unicodedata.east_asian_width(char) in ("W", "F")
                else 1
            )
        width += glyph
        last = glyph
    return width


def _pad(text: str, width: int, *, fill: str, align: str) -> str:
    """Pad ``text`` to a display ``width`` (no-op once it is already wider).

    Replaces the ``str`` format spec, whose padding counts code points.
    """
    deficit = width - display_width(text)
    if deficit <= 0:
        return text
    if align == ">":
        return fill * deficit + text
    if align == "^":
        left = deficit // 2
        return fill * left + text + fill * (deficit - left)
    return text + fill * deficit


def highlight_row(
    scoreboard: list[str],
    index: int,
    column_widths: list[int],
    *,
    has_header: bool = True,
) -> list[str]:
    """Prepend ``@`` to the rank column of the indexed row (in place).

    The marker is paid for by dropping one separator character, so the row
    keeps its width and the following columns stay on their offsets.
    """
    row_i = index + int(has_header)
    line = scoreboard[row_i]
    cut = _cell_end(line, column_widths[0])
    scoreboard[row_i] = "@" + line[:cut] + line[cut + 1 :]
    return scoreboard


# the scoreboard palette: neutral rows alternate, the focus row pops out
_ROW_COLORS = (ansi.WHITE, ansi.GRAY)
_HEADER_COLOR = ansi.BOLD_WHITE
_FOCUS_COLOR = ansi.BOLD_YELLOW


def colorize(
    scoreboard: list[str], highlight: int | None = None
) -> list[str]:
    """Wrap each line in its ANSI color (in place); header first.

    ``highlight`` is a data-row index, as in :func:`highlight_row`. The
    sequences add no display cells, so the columns keep their offsets, and
    a client that drops ANSI (mobile) still shows the aligned plain board.

    Call this *after* :func:`highlight_row` — the ``@`` splice counts
    characters, and escape sequences would be counted as cells.
    """
    scoreboard[0] = ansi.wrap(scoreboard[0], _HEADER_COLOR)
    for row_i, line in enumerate(scoreboard[1:]):
        color = (
            _FOCUS_COLOR
            if row_i == highlight
            else _ROW_COLORS[row_i % len(_ROW_COLORS)]
        )
        scoreboard[row_i + 1] = ansi.wrap(line, color)
    return scoreboard


def _cell_end(line: str, width: int) -> int:
    """Index just past the first ``width`` display cells of ``line``."""
    seen = 0
    for i, char in enumerate(line):
        if seen >= width:
            return i
        seen += display_width(char)
    return len(line)


_NO_CAP = 999


def calc_max_col_width(
    entries: Sequence[Sequence[str | int]],
    headers: list[str] | None = None,
    max_padding: list[int] | None = None,
) -> list[int]:
    """Per-column max rendered width (commas for ints, header respected).

    Widths are display widths (:func:`display_width`), so a wide name is
    measured by the cells it occupies rather than its code points.
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
        widest_val = max(display_width(cell) for cell in entire_col)
        width = min(
            max(widest_val, display_width(headers[col])), caps[col]
        )
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
    color: bool = True,
) -> FocusBoard | None:
    """The highlighted scoreboard around ``focus_uid``'s row; None when absent.

    Shared by the exp and frogs personal cards: focus-subset the ranked
    rows, resolve names, render with :func:`format` (highlighting the
    focus row) and expose the focus row's rank/value(/level) for the
    surrounding stats. ``level_of`` renders an extra Level column (exp
    cards); frogs' count card passes none. ``color`` emits ANSI row colors,
    so the text belongs in an ```` ```ansi ```` fence.
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
            color=color,
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
