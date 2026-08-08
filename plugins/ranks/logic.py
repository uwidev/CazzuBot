"""Ranks plugin — rank-change decisions + formatting (pure, no discord).

``plan_rank_changes`` computes the role adds/removes and the rank-up
notification flag from plain values (role *ids*, not role objects); the
side effects (role mutation, message send) live in
``plugins/ranks/presenter.py`` at the controller edge.
"""

from __future__ import annotations

from dataclasses import dataclass

from cazzubot.db import Database
from cazzubot.models import MemberSnapshot
from cazzubot.utils import OldNew

from . import db as ranks_db
from .db import RankThreshold


@dataclass(frozen=True)
class RankPlan:
    """What one window's rank change must do — plain role ids only.

    ``notify`` means the level crossed a threshold (rank-up message due);
    the presenter still resolves the id and skips when the role is missing.
    """

    add_ids: list[int]
    remove_ids: list[int]
    notify: bool
    rid_old: int | None
    rid_new: int | None
    level_old: int
    level_new: int


def plan_rank_changes(
    level: OldNew,
    thresholds: list[RankThreshold],
    *,
    keep_old: bool,
    notify: bool,
    member_role_ids: list[int],
) -> RankPlan:
    """Compute rank role adds/removes + notification flag for one window."""
    rid_new, idx_new = ranks_db.calc_min_rank(thresholds, level.new)
    rid_old, _idx_old = ranks_db.calc_min_rank(thresholds, level.old)
    ids = [row.rid for row in thresholds]

    # calc_min_rank returns (None, None) together, so rid_new and idx_new
    # are either both None or both set.
    if rid_new is not None and idx_new is not None:
        if keep_old:
            add_ids = ids[: idx_new + 1]
            remove_ids = ids[idx_new + 1 :]
        else:
            add_ids = [rid_new]
            remove_ids = ids[:idx_new] + ids[idx_new + 1 :]
    else:
        add_ids = []
        remove_ids = ids

    return RankPlan(
        add_ids=[r for r in add_ids if r not in member_role_ids],
        remove_ids=[r for r in remove_ids if r in member_role_ids],
        notify=notify and rid_new is not None and rid_new != rid_old,
        rid_old=rid_old,
        rid_new=rid_new,
        level_old=level.old,
        level_new=level.new,
    )


def rank_difference(
    level: OldNew, thresholds: list[RankThreshold]
) -> tuple[OldNew, OldNew]:
    """(rid_old->rid_new, index_old->index_new) across the thresholds."""
    rid_new, idx_new = ranks_db.calc_min_rank(thresholds, level.new)
    rid_old, idx_old = ranks_db.calc_min_rank(thresholds, level.old)
    return OldNew(rid_old, rid_new), OldNew(idx_old, idx_new)


async def is_ranked_up(db: Database, level: OldNew) -> bool:
    """True if going level.old -> level.new crosses a rank threshold."""
    thresholds = await ranks_db.get(db)
    if not thresholds:
        return False
    _, index = rank_difference(level, thresholds)
    return index.new != index.old


def formatter(
    s: str,
    *,
    member: MemberSnapshot,
    rank_old: str | None = None,
    rank_new: str | None = None,
    level_old: int | None = None,
    level_new: int | None = None,
) -> str:
    """Placeholders: {avatar} {name} {mention} {id} {rank_old} {rank_new}
    {level_old} {level_new} — ``rank_old``/``rank_new`` are mention strings
    (the presenter resolves ids; the service layer stays object-free)."""
    return s.format(
        avatar=member.avatar_url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        rank_old=rank_old,
        rank_new=rank_new,
        level_old=level_old,
        level_new=level_new,
    )
