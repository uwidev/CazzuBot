"""Converter to parses natural relative date/time language to a future DateTime object.

Also supports natural language for absolute date/time.

TODO  [ ]   Need to make sure timezone is independent from host. In other words,
            timezone needs to be explicitly set, probably to UTC.
      [ ]   Timezones should be able to be set as a setting for users.
"""
import re
from typing import Annotated

import parsedatetime
import pendulum


shorthand_relative_time = re.compile(r"(\d+w|\d+d|\d+h|\d+m|\d+s)(?=\w?)(?=\d|$)")
shorthand_tmr = re.compile(r"tmr")


def future_time(arg: str) -> pendulum.DateTime:
    """Convert a string to a datetime object.

    Handles relative and absolute date/time.

    parseDT() is unable to read "4d2h"-like formats, therefore we need to transform them
    to something that can be read, in this case, "4d 2h".

    Also does other transformations for more short-hand writing.
    """
    sub_filters = {
        (shorthand_relative_time.sub, r"\g<1> "),
        (shorthand_tmr.sub, r"tomorrow"),
    }

    transformed_arg = arg
    for func, to_sub in sub_filters:
        transformed_arg = func(to_sub, transformed_arg)

    datetime_obj, parse_status = parsedatetime.Calendar().parseDT(
        transformed_arg,
        sourceTime=pendulum.now(),
    )

    if not parse_status:
        raise InvalidTimeError(arg)

    return pendulum.parser.parse(str(datetime_obj))


class InvalidTimeError(Exception):
    def __init__(self, arg):
        msg = f"{arg} is not a valid time"
        super().__init__(msg)


FutureTime = Annotated[pendulum.DateTime, future_time]
