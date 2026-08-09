"""Natural Time Language Parsing (port of v1's ``src/ntlp.py``).

Parses natural relative/absolute time language into UTC ``pendulum.DateTime``.
The bot always computes in UTC; timezone conversion happens only at the user
boundary.
"""

import logging
import re
from datetime import datetime
from typing import cast

import parsedatetime
import pendulum

_log = logging.getLogger(__name__)

# "4d2h"-style glued shorthands get spaces inserted
_any_shorthand_time = re.compile(
    r"(\d+w|\d+d|\d+h|\d+m|\d+s)(?=\w?)(?=\d|$)"
)
_shorthand_tmr = re.compile(r"tmr")

# Shared duration-unit vocabulary. ``parse_duration`` derives its
# per-unit shorthand patterns from it, and the mod plugin's duration-token
# guard (``plugins/mod/logic.py``) builds on ``DURATION_UNITS`` — one
# source so the two never drift apart.
_DURATION_UNIT_ALTERNATIONS: dict[str, str] = {
    "years": r"years?|y",
    "months": r"months?|M",
    "weeks": r"weeks?|w",
    "days": r"days?|d",
    "hours": r"hours?|hrs?|h",
    "minutes": r"minutes?|mins?|m",
    "seconds": r"seconds?|secs?|s",
}

# Bare-unit alternation for embedding in other patterns (e.g. the mod
# plugin's token guard): "(?:years?|y|...)".
DURATION_UNITS = "|".join(
    f"(?:{alt})" for alt in _DURATION_UNIT_ALTERNATIONS.values()
)

_SHORTHAND_PATTERNS: dict[str, re.Pattern[str]] = {
    unit: re.compile(rf"(\d+)\s*({alt})")
    for unit, alt in _DURATION_UNIT_ALTERNATIONS.items()
}
# seconds keeps the end-anchored, unit-optional form so a bare number
# ("90") still reads as 90 seconds
_SHORTHAND_PATTERNS["seconds"] = re.compile(
    rf"(\d+)\s*({_DURATION_UNIT_ALTERNATIONS['seconds']})?$"
)


class InvalidTimeError(Exception):
    """Raised when a string cannot be parsed as a time."""


class NotFutureError(Exception):
    """Raised when a parsed time is not in the future."""


def normalize_time_str(arg: str) -> pendulum.DateTime:
    """Parse natural language into a UTC DateTime.

    Supports relative ("2 hours from now") and absolute ("tomorrow 5pm",
    "2026-05-01") phrasing. Raises ``InvalidTimeError`` on failure.
    """
    arg = _shorthand_tmr.sub("tomorrow", _spaces_out_shorthands(arg))
    cal = parsedatetime.Calendar()
    parsed, status = cast(
        tuple[datetime, int],
        cal.parseDT(arg, sourceTime=pendulum.now("UTC").naive()),
    )
    if not status:
        raise InvalidTimeError(f"{arg} is not a valid time")
    # parseDT returns a naive datetime in the source timezone (UTC)
    return pendulum.instance(parsed).in_tz("UTC")


def parse_duration(arg: str) -> pendulum.Duration:
    """Parse a duration ("2h", "1d 30m", "3 weeks") into a Duration."""
    payload: dict[str, int] = {}
    for unit, pattern in _SHORTHAND_PATTERNS.items():
        match = pattern.search(arg)
        if match:
            payload[unit] = int(match.group(1))

    if not payload:
        raise InvalidTimeError(f"{arg} is not a valid time")

    duration = pendulum.duration(**payload)
    if duration.in_seconds() == 0:
        raise InvalidTimeError(f"{arg} is not a valid time")
    return duration


def parse_iso8601(raw: str) -> pendulum.DateTime:
    """Parse an ISO-8601 timestamp we stored (always a UTC DateTime)."""
    return cast(pendulum.DateTime, pendulum.parse(raw))


def is_future(past: pendulum.DateTime, future: pendulum.DateTime) -> bool:
    return past < future


def _spaces_out_shorthands(arg: str) -> str:
    return _any_shorthand_time.sub(r" \1 ", arg)
