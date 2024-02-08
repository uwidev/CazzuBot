"""Natural Time Language Processing (NTLP/ntlp).

Parses natural relative date/time language to a DateTime object.

Also supports natural language for absolute date/time.

Bot should always calculate in UCT timezone, only changing timezone when interacing
with users. This mean that time should always be converted when users input time, and
when outputting time.

TODO  [ ]   Timezones should be able to be set as a setting for users.
"""

import logging
import re
from typing import Annotated

import parsedatetime
import pendulum


_log = logging.getLogger(__name__)


shorthand_relative_time = re.compile(r"(\d+w|\d+d|\d+h|\d+m|\d+s)(?=\w?)(?=\d|$)")
shorthand_tmr = re.compile(r"tmr")
shorhand_patterns = {
    "years": r"(\d+)\s*(year|y)",
    "months": r"(\d+)\s*(month|M)",
    "days": r"(\d+)\s*(day|d)",
    "hours": r"(\d+)\s*(hour|h)",
    "minutes": r"(\d+)\s*(minute|m)",
    "seconds": r"(\d+)\s*(second|s)",
}

for k in shorhand_patterns:  # compile for efficiency
    shorhand_patterns[k] = re.compile(shorhand_patterns[k])


def normalize_time_str(s: str) -> pendulum.DateTime:
    """Convert a string to a datetime object.

    Handles relative AND absolute date/time.

    parseDT() is unable to read "4d2h"-like formats, therefore we need to transform them
    to something that can be read, in this case, "4d 2h".

    Also does other transformations for more short-hand writing.
    """
    sub_filters = {
        (shorthand_relative_time.sub, r"\g<1> "),  # add the space
        (shorthand_tmr.sub, r"tomorrow"),
    }

    transformed_arg = s
    for func, to_sub in sub_filters:
        transformed_arg = func(to_sub, transformed_arg)

    datetime_obj, parse_status = parsedatetime.Calendar().parseDT(
        transformed_arg,
        sourceTime=pendulum.now(tz="UTC"),  # Force UCT, ignore local machine
    )

    if not parse_status:
        raise InvalidTimeError(s)

    return pendulum.parser.parse(str(datetime_obj))


def is_future(past: pendulum.DateTime, future: pendulum.DateTime):
    """Check if the second argument is a future time of the first."""
    return past < future


def parse_duration(s: str) -> pendulum.DateTime:
    """Parse natural language duration into timedelta duration object.

    Supports years to seconds.
    """
    payload = dict()
    for key, pattern in shorhand_patterns.items():
        match = re.search(pattern, s)
        payload[key] = int(match.group(1)) if match else 0

    duration = pendulum.duration(**payload)

    if duration.in_seconds() == 0:
        raise InvalidTimeError(s)

    return duration


class InvalidTimeError(Exception):
    def __init__(self, arg):
        msg = f"{arg} is not a valid time"
        super().__init__(msg)


class NotFutureError(Exception):
    def __init__(self, arg):
        msg = f"{arg} is not a time in the future!"
        super().__init__(msg)


# To support type-hinting and discord.py conversions
NormalizedTime = Annotated[pendulum.DateTime, normalize_time_str]
