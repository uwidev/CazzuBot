"""Ranks service (logic) layer — ported from scripts/functest.py."""

from __future__ import annotations

from cazzubot.models import WindowEnum
from cazzubot.utils import OldNew
from plugins.ranks.db import RankThreshold
from plugins.ranks.logic import rank_difference

_THRESHOLDS = [
    RankThreshold(rid=111, threshold=5, mode=WindowEnum.SEASONAL),
    RankThreshold(rid=222, threshold=10, mode=WindowEnum.SEASONAL),
    RankThreshold(rid=333, threshold=20, mode=WindowEnum.SEASONAL),
]


def test_rank_difference_across_thresholds() -> None:
    diffs = rank_difference(OldNew(6, 12), _THRESHOLDS)
    assert diffs[0].old == 111 and diffs[0].new == 222, diffs
    assert diffs[1].old == 0 and diffs[1].new == 1, diffs
