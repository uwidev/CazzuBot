"""Level math — ported from scripts/functest.py."""

from __future__ import annotations

from cazzubot import levels


def test_level_from_exp_edges() -> None:
    assert levels.level_from_exp(0) == 0
    assert levels.level_from_exp(10_000) > 0


def test_cumulative_increases_with_level() -> None:
    assert levels.exp_to_level_cum(5) > 0
    assert levels.exp_to_level_cum(10) > levels.exp_to_level_cum(5)
