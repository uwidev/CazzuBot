"""core.leaderboard — column alignment, the dotted fill, and highlight."""

from core import leaderboard

_HEADERS = ["Rank", "Exp", "Lv", "User"]
_ALIGN = ["<", ">", ">", ">"]
_CAPS = [0, 0, 0, 16]
_ENTRIES = [
    (1, 49641, 78, "kirisame"),
    (2, 42305, 71, "sakuya"),
    (3, 38214, 68, "usara"),
    (4, 37264, 67, "れいむ"),
    (5, 33683, 64, "cirno"),
]
_LONG_NAME = "marisa_kirisame_the_ordinary"


def _cells(line: str, widths: list[int], spacing: int = 2) -> list[str]:
    """The column regions of a rendered line, fill stripped."""
    cells: list[str] = []
    pos = 0
    for width in widths:
        cells.append(line[pos : pos + width].strip(". "))
        pos += width + spacing
    return cells


def _plain() -> list[str]:
    """The unhighlighted board over the fixture entries."""
    return leaderboard.format(
        _ENTRIES, _HEADERS, align=_ALIGN, max_padding=_CAPS
    )


def test_rows_alternate_dotted_and_plain_fill() -> None:
    lines = leaderboard.format(
        [(1, 42, "bob"), (2, 7, "ann")],
        ["Rank", "Exp", "User"],
        align=["<", ">", ">"],
    )
    assert lines == [
        "Rank  Exp  User",
        "1......42...bob",
        "2       7   ann",
    ]


def test_columns_keep_their_offsets_on_every_row() -> None:
    """Regression: odd rows joined cells with an empty separator, so the
    values of neighbouring columns ran together ("98,76530")."""
    widths = leaderboard.calc_max_col_width(_ENTRIES, _HEADERS, _CAPS)
    lines = _plain()
    expected = [
        [f"{val:,}" if isinstance(val, int) else val for val in row]
        for row in _ENTRIES
    ]
    assert [_cells(line, widths) for line in lines[1:]] == expected


def test_highlight_keeps_the_next_column_intact() -> None:
    """Regression: the ``@`` used to consume a character of the following
    column (``37,264`` rendered as ``7,264``)."""
    plain = _plain()
    lines = leaderboard.format(
        _ENTRIES, _HEADERS, align=_ALIGN, max_padding=_CAPS, highlight=3
    )
    assert lines[4].startswith("@4")
    assert "37,264" in lines[4]
    # the marker is paid for out of the separator: same width, and every
    # column after the rank still sits where the unmarked board puts it
    assert leaderboard.display_width(
        lines[4]
    ) == leaderboard.display_width(plain[4])
    assert lines[4][6:] == plain[4][6:]


def test_highlight_works_on_a_dotted_row() -> None:
    plain = _plain()
    lines = leaderboard.format(
        _ENTRIES, _HEADERS, align=_ALIGN, max_padding=_CAPS, highlight=0
    )
    assert lines[1].startswith("@1")
    assert "49,641" in lines[1]
    assert lines[1][6:] == plain[1][6:]


def test_display_width_counts_wide_cells() -> None:
    assert leaderboard.display_width("cirno") == 5
    assert leaderboard.display_width("れいむ") == 6
    assert leaderboard.display_width("cirno🐸") == 7


def test_display_width_collapses_joined_glyphs() -> None:
    assert leaderboard.display_width("🇯🇵") == 2
    assert leaderboard.display_width("usara❤️") == 7
    assert leaderboard.display_width("👨‍👩‍👧") == 2
    assert leaderboard.display_width("e\u0301") == 1


def test_wide_names_are_padded_by_cells_not_code_points() -> None:
    lines = leaderboard.format(
        [(1, 10, "れいむ"), (2, 5, "ann")],
        ["Rank", "Exp", "User"],
        align=["<", ">", ">"],
    )
    widths = {leaderboard.display_width(line) for line in lines}
    assert len(widths) == 1


def test_max_padding_caps_the_column_but_never_truncates() -> None:
    entries = [(1, 10, 1, _LONG_NAME), (2, 5, 1, "ann")]
    assert (
        leaderboard.calc_max_col_width(entries, _HEADERS, _CAPS)[3] == 16
    )
    # 0 is the "no cap" sentinel
    assert leaderboard.calc_max_col_width(entries, _HEADERS, [0, 0, 0, 0])[
        3
    ] == len(_LONG_NAME)
    lines = leaderboard.format(
        entries, _HEADERS, align=_ALIGN, max_padding=_CAPS
    )
    assert _LONG_NAME in lines[1]
