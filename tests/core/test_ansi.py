"""core.ansi — SGR wrapping and stripping for the scoreboard's row colors."""

from core import ansi


def test_wrap_resets_after_the_text() -> None:
    assert ansi.wrap("hi", ansi.WHITE) == "\x1b[0;37mhi\x1b[0m"


def test_strip_removes_every_sequence() -> None:
    colored = ansi.wrap(ansi.wrap("hi", ansi.GRAY), ansi.BOLD_WHITE)
    assert ansi.strip(colored) == "hi"
    assert ansi.strip("plain") == "plain"


def test_strip_leaves_other_escapes_alone() -> None:
    # only SGR sequences (the …m family) are color
    assert ansi.strip("\x1b[2J") == "\x1b[2J"
