"""Mod service layer — pure decision helpers, no discord objects.

Mirrors ``plugins/experience/logic.py``: plain-data functions only. The mod
commands are deliberately thin controllers (resolve discord objects, apply
roles, schedule expiries, window feedback); the *decisions* — duration
parsing, future validation, ban-vs-tempban — live here.
"""

from __future__ import annotations

import pendulum
from discord.ext import commands

from cazzubot.models import ModlogTypeEnum
from cazzubot.timeparse import (
    InvalidTimeError,
    is_future,
    normalize_time_str,
)


def split_duration_reason(
    raw: str | None,
) -> tuple[pendulum.DateTime | None, str]:
    """Parse an optional leading duration from the rest of the string.

    The duration must be a single token ("2h", "tomorrow", "2026-05-01").
    Multi-word phrasings ("2 hours ...") don't parse and fall back to no
    duration — a mute/ban without expiry.
    """
    if not raw:
        return None, ""
    if " " in raw:
        dur_raw, rest = raw.split(" ", 1)
    else:
        dur_raw, rest = raw, ""
    try:
        return normalize_time_str(dur_raw), rest
    except InvalidTimeError:
        return None, raw


def ensure_future(
    now: pendulum.DateTime, duration: pendulum.DateTime | None
) -> None:
    """Raise ``BadArgument`` when a parsed duration isn't in the future."""
    if duration and not is_future(now, duration):
        raise commands.BadArgument(
            f"{duration} is not a time in the future!"
        )


def resolve_ban_type(
    duration: pendulum.DateTime | None,
) -> ModlogTypeEnum:
    """A duration makes a ban temporary; without one, permanent."""
    return ModlogTypeEnum.TEMPBAN if duration else ModlogTypeEnum.BAN
