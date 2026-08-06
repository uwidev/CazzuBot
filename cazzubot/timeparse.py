"""Natural Time Language Parsing (port of v1's ``src/ntlp.py``).

Parses natural relative/absolute time language into UTC ``pendulum.DateTime``.
The bot always computes in UTC; timezone conversion happens only at the user
boundary.
"""

import logging
import re
from datetime import datetime
from typing import Annotated, cast

import parsedatetime
import pendulum

_log = logging.getLogger(__name__)

# "4d2h"-style glued shorthands get spaces inserted
_any_shorthand_time = re.compile(
    r"(\d+w|\d+d|\d+h|\d+m|\d+s)(?=\w?)(?=\d|$)"
)
_shorthand_tmr = re.compile(r"tmr")

_SHORTHAND_PATTERNS: dict[str, re.Pattern[str]] = {
    "years": re.compile(r"(\d+)\s*(year[s]|y)"),
    "months": re.compile(r"(\d+)\s*(month[s]|M)"),
    "weeks": re.compile(r"(\d+)\s*(week[s]|w)"),
    "days": re.compile(r"(\d+)\s*(day[s]|d)"),
    "hours": re.compile(r"(\d+)\s*(hour[s]|h)"),
    "minutes": re.compile(r"(\d+)\s*(minute[s]|m)"),
    "seconds": re.compile(r"(\d+)\s*(second[s]|s)?$"),
}


class InvalidTimeError(Exception):
    """Raised when a string cannot be parsed as a time."""


class NotFutureError(Exception):
    """Raised when a parsed time is not in the future."""


def _spaces_out_shorthands(arg: str) -> str:
    return _any_shorthand_time.sub(r" \1 ", arg)


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


def is_future(past: pendulum.DateTime, future: pendulum.DateTime) -> bool:
    return past < future


def parse_iso8601(raw: str) -> pendulum.DateTime:
    """Parse an ISO-8601 timestamp we stored (always a UTC DateTime)."""
    return cast(pendulum.DateTime, pendulum.parse(raw))


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


NormalizedTime = Annotated[pendulum.DateTime, normalize_time_str]
