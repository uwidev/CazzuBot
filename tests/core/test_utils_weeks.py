"""cazzubot.utils week math — Sunday/Monday starts, numbers, round-trips."""

import pendulum
import pytest

from cazzubot.errors import UserInputError
from cazzubot.utils import week_number, week_start, week_start_of


def test_week_start_monday() -> None:
    now = pendulum.datetime(2026, 8, 19, 14, 30, tz="UTC")  # Wednesday
    assert week_start(now, start="monday") == pendulum.datetime(
        2026, 8, 17, tz="UTC"
    )


def test_week_start_sunday() -> None:
    now = pendulum.datetime(2026, 8, 19, 14, 30, tz="UTC")
    assert week_start(now, start="sunday") == pendulum.datetime(
        2026, 8, 16, tz="UTC"
    )


def test_week_start_sunday_on_a_sunday() -> None:
    now = pendulum.datetime(2026, 8, 16, 14, 0, tz="UTC")
    assert week_start(now, start="sunday") == pendulum.datetime(
        2026, 8, 16, tz="UTC"
    )


def test_week_start_of_iso_week() -> None:
    # ISO week 33 of 2026 = Mon 2026-08-10 .. Sun 2026-08-16
    assert week_start_of(2026, 33, start="monday") == pendulum.datetime(
        2026, 8, 10, tz="UTC"
    )
    # Sunday-start weeks begin on the Sunday that ends the ISO week
    assert week_start_of(2026, 33, start="sunday") == pendulum.datetime(
        2026, 8, 16, tz="UTC"
    )


def test_week_number_matches_iso_for_monday_start() -> None:
    now = pendulum.datetime(2026, 8, 19, tz="UTC")
    assert week_number(now, start="monday") == (34, 2026)
    assert week_number(now, start="sunday") == (33, 2026)


@pytest.mark.parametrize("start", ["sunday", "monday"])
def test_week_start_round_trip_every_day_of_a_month(start: str) -> None:
    """week_start_of(year, week_number(now)) recovers week_start(now)."""
    for day in range(1, 29):
        now = pendulum.datetime(2026, 8, day, 12, 0, tz="UTC")
        week, year = week_number(now, start=start)
        assert week_start_of(year, week, start=start) == week_start(
            now, start=start
        )


def test_week_start_of_rejects_bad_weeks() -> None:
    with pytest.raises(UserInputError):
        week_start_of(2026, 0)
    with pytest.raises(UserInputError):
        week_start_of(2026, 54)
    with pytest.raises(UserInputError):
        week_start_of(2027, 53)  # 2027 only has 52 ISO weeks


def test_week_start_rejects_bad_start() -> None:
    now = pendulum.datetime(2026, 8, 19, tz="UTC")
    with pytest.raises(UserInputError):
        week_start(now, start="friday")
