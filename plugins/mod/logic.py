"""Mod service layer — pure decision helpers, no discord objects.

Mirrors ``plugins/experience/logic.py``: plain-data functions only. The mod
commands are deliberately thin controllers (resolve discord objects, apply
roles, schedule expiries, window feedback); the *decisions* — duration
parsing, future validation, ban-vs-tempban — live here.
"""

from __future__ import annotations

import re

import pendulum

from cazzubot.errors import UserInputError
from cazzubot.models import ModlogTypeEnum
from cazzubot.timeparse import (
    DURATION_UNITS,
    InvalidTimeError,
    is_future,
    normalize_time_str,
)

# Why a token guard at all? ``normalize_time_str`` (parsedatetime) only
# errors when it finds NO date/time token ("no duration" -> status 0);
# around a valid time it silently discards junk, so "2 hours being bad"
# parses exactly like "2 hours". Its status is a coarse date/time bitmask
# with no "characters consumed" info, so greedy matching "until the
# parser errors" would swallow the whole string as the duration and
# delete the reason. These regexes are only a token classifier deciding
# where the duration ends; the time math still goes through
# ``normalize_time_str``, and unparseable candidates still fall back to
# no duration.
#
# Tokens that can extend a duration after the first parseable prefix:
# bare quantities ("5", "2026", "1st", "5pm"), quantity+unit ("5m"),
# and bare units ("minutes") which only follow a bare quantity
# ("2 hours 5 minutes" extends; "2 hours minutes" does not). Reason
# words ("being", "bad") never match and stop the extension. The unit
# vocabulary is shared with ``parse_duration`` (cazzubot/timeparse.py).
_DURATION_AMOUNT = re.compile(
    r"^\d+(\.\d+)?(st|nd|rd|th)?(am|pm)?$", re.IGNORECASE
)
_DURATION_AMOUNT_UNIT = re.compile(
    rf"^\d+(\.\d+)?(st|nd|rd|th)?\s*(?:{DURATION_UNITS})$",
    re.IGNORECASE,
)
_DURATION_UNIT = re.compile(rf"^(?:{DURATION_UNITS})$", re.IGNORECASE)


def split_duration_reason(
    raw: str | None,
) -> tuple[pendulum.DateTime | None, str]:
    """Parse an optional leading duration from the rest of the string.

    The duration is the first leading prefix that parses, extended
    greedily over duration-like tokens ("2h", "tomorrow", "2026-05-01",
    "in 2 hours", "2 hours 5 minutes", "tomorrow 5pm") — natural
    multi-word phrasing no longer silently becomes a mute/ban without
    expiry. Extending stops at the first non-duration token, which starts
    the reason. When no prefix parses, the whole string is the reason.
    """
    if not raw:
        return None, ""
    tokens = raw.split(" ")
    duration: pendulum.DateTime | None = None
    for end in range(1, len(tokens) + 1):
        try:
            duration = normalize_time_str(" ".join(tokens[:end]))
        except InvalidTimeError:
            continue
        break
    if duration is None:
        return None, raw
    while end < len(tokens) and _extends_duration(tokens, end):
        try:
            duration = normalize_time_str(" ".join(tokens[: end + 1]))
        except InvalidTimeError:
            break
        end += 1
    return duration, " ".join(tokens[end:])


def ensure_future(
    now: pendulum.DateTime, duration: pendulum.DateTime | None
) -> None:
    """Raise ``UserInputError`` when a duration isn't in the future."""
    if duration and not is_future(now, duration):
        raise UserInputError(f"{duration} is not a time in the future!")


def resolve_ban_type(
    duration: pendulum.DateTime | None,
) -> ModlogTypeEnum:
    """A duration makes a ban temporary; without one, permanent."""
    return ModlogTypeEnum.TEMPBAN if duration else ModlogTypeEnum.BAN


def _extends_duration(tokens: list[str], end: int) -> bool:
    """Can the token at ``end`` extend the parsed duration prefix?"""
    token = tokens[end]
    if _DURATION_AMOUNT_UNIT.match(token) or _DURATION_AMOUNT.match(token):
        return True
    # a bare unit extends only after a bare quantity, so "2 hours 5
    # minutes" folds in but "2 hours minutes" leaves "minutes" as reason
    return bool(
        _DURATION_UNIT.match(token)
        and _DURATION_AMOUNT.match(tokens[end - 1])
    )
