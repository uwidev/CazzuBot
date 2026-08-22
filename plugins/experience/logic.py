"""Experience service layer — pure exp logic, no discord objects.

Mirrors ``plugins/ranks/logic.py``: service functions take ``db`` + plain
values + injected ``now`` and return plain results, so they are unit-testable
without discord fakes. The extension (controller) translates discord objects into
plain values, calls this layer, and handles presentation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pendulum

from cazzubot import levels
from cazzubot.db import Database
from cazzubot.member_effects import (
    MemberEffectKey,
    get as member_effects_get,
)
from cazzubot.utils import OldNew, month2season

from . import db as exp_db

# -- experience rates (hard-coded; restart the bot to change) --------------

_BASE = 1
_BONUS = 20
_UNTIL_MSG = 77
_DECAY_FACTOR = 2
_EXP_COOLDOWN = 15  # seconds


def from_msg(msg: int) -> int:
    """Expected exp reward for the message at daily count ``msg``."""
    if msg < 0:
        raise ValueError("Negative messages should not exist")
    if msg >= _UNTIL_MSG:
        return _BASE
    return round(
        (_BASE * _BONUS)
        - (_BASE * _BONUS - _BASE) * (msg / _UNTIL_MSG) ** _DECAY_FACTOR
    )


@dataclass(frozen=True)
class ExpAward:
    """What one message award did — the controller's presentation input."""

    uid: int
    exp_gain: int
    msg_cnt: int
    seasonal_level: OldNew
    lifetime_level: OldNew


async def award_exp(
    db: Database, *, uid: int, now: pendulum.DateTime
) -> ExpAward | None:
    """Award exp for one message; ``None`` when the cooldown is active.

    Pure read-modify-write over ``db`` with injected ``now`` — no discord
    objects, no bot. Level-up/rank-up notifications are the controller's job,
    fed by the returned ``ExpAward``.
    """
    member_db = await exp_db.get_member_exp(db, uid)
    if member_db is None:
        await exp_db.add_member_exp(
            db, uid, cdr=now.subtract(hours=1).isoformat()
        )
        member_db = await exp_db.get_member_exp(db, uid)
        assert member_db is not None  # the insert just created the row

    cdr = member_db.cdr
    if cdr and now < cdr:
        return None  # cooldown not yet expired

    # compute gains
    msg_cnt = member_db.msg_cnt + 1
    exp_gain = from_msg(msg_cnt)
    # a member modifier (e.g. the exp_multiplier buff) scales the award —
    # pulled lazily here, so no sweeper is needed for expiry
    multiplier = await member_effects_get(
        db, uid, MemberEffectKey.EXP_MULTIPLIER, now=now
    )
    if multiplier is not None:
        exp_gain = round(exp_gain * multiplier)
    year, season = now.year, month2season(now.month)

    seasonal_old = await exp_db.seasonal_exp(db, uid, year, season)
    seasonal_new = seasonal_old + exp_gain
    lifetime_old = member_db.lifetime
    lifetime_new = lifetime_old + exp_gain

    # persist
    await exp_db.update_member_exp(
        db,
        uid,
        lifetime=lifetime_new,
        msg_cnt=msg_cnt,
        cdr=now.add(seconds=_EXP_COOLDOWN),
    )
    await exp_db.add_exp_log(db, uid, exp_gain, now)

    return ExpAward(
        uid=uid,
        exp_gain=exp_gain,
        msg_cnt=msg_cnt,
        seasonal_level=OldNew(
            levels.level_from_exp(seasonal_old),
            levels.level_from_exp(seasonal_new),
        ),
        lifetime_level=OldNew(
            levels.level_from_exp(lifetime_old),
            levels.level_from_exp(lifetime_new),
        ),
    )
