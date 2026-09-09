"""ANSI SGR colors for Discord code blocks.

Discord only renders these inside an ```` ```ansi ```` fence; clients that
drop ANSI (the mobile apps) swallow the sequences and show the plain text,
so color is always decoration on top of text that already reads on its own.
A sequence occupies no display cells (see
:func:`core.leaderboard.display_width`).

Depended on by: ``core.leaderboard`` (the scoreboard's row colors).
"""

import re

# text colors (SGR 30-37)
GRAY = "\x1b[0;30m"
RED = "\x1b[0;31m"
GREEN = "\x1b[0;32m"
YELLOW = "\x1b[0;33m"
BLUE = "\x1b[0;34m"
PINK = "\x1b[0;35m"
CYAN = "\x1b[0;36m"
WHITE = "\x1b[0;37m"

# emphasis variants (SGR 1 = bold)
BOLD_WHITE = "\x1b[1;37m"
BOLD_YELLOW = "\x1b[1;33m"

RESET = "\x1b[0m"

_SEQUENCE = re.compile(r"\x1b\[[0-9;]*m")


def wrap(text: str, color: str) -> str:
    """``text`` in ``color``, reset afterwards."""
    return f"{color}{text}{RESET}"


def strip(text: str) -> str:
    """``text`` with every SGR sequence removed."""
    return _SEQUENCE.sub("", text)
