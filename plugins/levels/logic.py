"""Levels plugin — level-up decision + formatting (pure, no discord).

The *decision* (skip / reaction / message) and the *formatting* live here
over plain values; the side effects (reaction, send) live in
``plugins/levels/presenter.py`` at the controller edge.
"""

from __future__ import annotations

from enum import Enum

from cazzubot.models import MemberSnapshot
from cazzubot.utils import OldNew, format_member

MESSAGE_KEY = "level.message"


class LevelUpAction(Enum):
    """What the level-up pipeline should do for one message."""

    SKIP = "skip"  # no level gain, or a rank-up trumps the level-up
    REACTION = "reaction"  # quiet channel — react instead of sending
    MESSAGE = "message"  # send the configured level-up template


def decide_level_up(
    level: OldNew,
    *,
    ranked_up: bool,
    channel_id: int,
    quiet_ids: list[int],
) -> LevelUpAction:
    """What to do when a member's level changed from ``level.old``.

    ``ranked_up`` is the caller's answer to "did this exp gain cross a rank
    threshold" (a db-backed check — ``plugins.ranks.logic.is_ranked_up``).
    """
    if level.new <= level.old:
        return LevelUpAction.SKIP
    if ranked_up:
        return LevelUpAction.SKIP  # rank up trumps level up
    if channel_id in quiet_ids:
        return LevelUpAction.REACTION
    return LevelUpAction.MESSAGE


def formatter(
    s: str,
    *,
    member: MemberSnapshot,
    level_old: int | None = None,
    level_new: int | None = None,
) -> str:
    """Placeholders: {avatar} {name} {mention} {id} {level_old} {level_new}"""
    return format_member(
        s,
        member,
        level_old=level_old,
        level_new=level_new,
    )
