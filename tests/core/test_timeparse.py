"""Time parsing — ported from scripts/functest.py."""

from __future__ import annotations

import pendulum
import pytest

from cazzubot import timeparse


def test_normalize_time_str() -> None:
    dt = timeparse.normalize_time_str("2 hours from now")
    assert dt > pendulum.now("UTC")


def test_parse_duration() -> None:
    dur = timeparse.parse_duration("1d 30m")
    assert dur.in_seconds() == 86400 + 1800


def test_parse_duration_rejects_garbage() -> None:
    with pytest.raises(timeparse.InvalidTimeError):
        timeparse.parse_duration("nonsense")
