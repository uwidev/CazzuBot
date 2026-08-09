"""Cadence — next/previous run math, the missed-run rule, and arming."""

from __future__ import annotations

import pendulum
import pytest

from cazzubot.bot import CazzuBot
from cazzubot.scheduler import Cadence

# 2026-08-10 is a Monday; 2026-08-16 is the following Sunday.
# pendulum weekday(): Monday=0 … Sunday=6.


def _dt(*, day: int, hour: int = 0, minute: int = 0) -> pendulum.DateTime:
    """An instant in the fixed test week (August 2026, UTC)."""
    return pendulum.datetime(2026, 8, day, hour, minute, tz="UTC")


def _parse_dt(iso: str) -> pendulum.DateTime:
    """Parse a stored ISO timestamp (pendulum.parse returns a union)."""
    parsed = pendulum.parse(iso)
    assert isinstance(parsed, pendulum.DateTime)
    return parsed


# -- next_run -------------------------------------------------------------


async def test_daily_next_run_later_today() -> None:
    assert Cadence("22:00").next_run(_dt(day=10, hour=13, minute=30)) == (
        _dt(day=10, hour=22)
    )


async def test_daily_next_run_tomorrow_after_time() -> None:
    assert Cadence("09:00").next_run(_dt(day=10, hour=13)) == _dt(
        day=11, hour=9
    )


async def test_daily_next_run_at_the_instant_rolls_to_tomorrow() -> None:
    """next_run is strictly future — arming at exactly 09:00 goes to day 2."""
    assert Cadence("09:00").next_run(_dt(day=10, hour=9)) == _dt(
        day=11, hour=9
    )


async def test_daily_next_run_midnight() -> None:
    assert Cadence("00:00").next_run(_dt(day=10, hour=23, minute=59)) == (
        _dt(day=11)
    )


async def test_weekly_next_run_rolls_forward_to_target_day() -> None:
    """Wednesday → next Monday."""
    assert Cadence("09:00", weekday=0).next_run(
        _dt(day=12, hour=13)
    ) == _dt(day=17, hour=9)


async def test_weekly_next_run_same_day_before_time() -> None:
    assert Cadence("09:00", weekday=0).next_run(
        _dt(day=10, hour=8)
    ) == _dt(day=10, hour=9)


async def test_weekly_next_run_same_day_after_time_rolls_a_week() -> None:
    assert Cadence("09:00", weekday=0).next_run(
        _dt(day=10, hour=10)
    ) == _dt(day=17, hour=9)


async def test_weekly_next_run_sunday_wrap() -> None:
    """Friday and Monday both land on the coming Sunday 00:00."""
    sunday = _dt(day=16)
    assert Cadence("00:00", weekday=6).next_run(
        _dt(day=14, hour=12)
    ) == sunday
    assert Cadence("00:00", weekday=6).next_run(
        _dt(day=10, hour=12)
    ) == sunday


# -- previous_run ---------------------------------------------------------


async def test_previous_run_daily_earlier_today() -> None:
    assert Cadence("09:00").previous_run(_dt(day=10, hour=13)) == (
        _dt(day=10, hour=9)
    )


async def test_previous_run_daily_yesterday_after_time() -> None:
    assert Cadence("22:00").previous_run(_dt(day=10, hour=13)) == (
        _dt(day=9, hour=22)
    )


async def test_previous_run_weekly_this_week() -> None:
    """Wednesday → this week's Monday."""
    assert Cadence("09:00", weekday=0).previous_run(
        _dt(day=12, hour=13)
    ) == _dt(day=10, hour=9)


async def test_previous_run_weekly_before_time_on_target_day() -> None:
    """Monday 08:00 → last week's Monday (today's 09:00 hasn't happened)."""
    assert Cadence("09:00", weekday=0).previous_run(
        _dt(day=10, hour=8)
    ) == _dt(day=3, hour=9)


async def test_previous_run_weekly_wrap_to_last_week() -> None:
    """Monday → the previous Sunday."""
    assert Cadence("00:00", weekday=6).previous_run(
        _dt(day=10, hour=12)
    ) == _dt(day=9)


# -- missed (the catch-up rule) --------------------------------------------


async def test_missed_true_when_last_run_predates_occurrence() -> None:
    """Last reset yesterday 20:00 — today's midnight never ran."""
    assert Cadence("00:00").missed(
        _dt(day=9, hour=20), _dt(day=10, hour=10)
    )


async def test_missed_false_when_occurrence_serviced() -> None:
    assert not Cadence("00:00").missed(
        _dt(day=10, hour=0), _dt(day=10, hour=10)
    )


async def test_missed_false_after_late_reset() -> None:
    """A reset after the occurrence (00:05) still covers it."""
    assert not Cadence("00:00").missed(
        _dt(day=10, hour=0, minute=5), _dt(day=10, hour=10)
    )


async def test_missed_weekly() -> None:
    """Last Sunday ran, this Sunday's 00:00 hasn't — missed."""
    cadence = Cadence("00:00", weekday=6)
    assert cadence.missed(_dt(day=9, hour=0), _dt(day=16, hour=10))
    assert not cadence.missed(_dt(day=16, hour=0), _dt(day=16, hour=10))


# -- validation ------------------------------------------------------------


async def test_cadence_validation() -> None:
    for bad in ("25:00", "9:00", "ab:cd", "00:60", ""):
        with pytest.raises(ValueError):
            Cadence(time=bad)
    for bad_weekday in (-1, 7):
        with pytest.raises(ValueError):
            Cadence(time="00:00", weekday=bad_weekday)
    # valid forms
    Cadence(time="00:00")
    Cadence(time="23:59", weekday=6)


# -- arming ----------------------------------------------------------------


async def test_arm_schedules_next_run(bot: CazzuBot) -> None:
    cadence = Cadence(time="00:00")
    await bot.scheduler.arm("cad", cadence)
    rows = await bot.scheduler.get("cad")
    assert len(rows) == 1
    assert _parse_dt(rows[0].run_at) == cadence.next_run(
        pendulum.now("UTC")
    )
    assert _parse_dt(rows[0].run_at) > pendulum.now("UTC")


async def test_arm_drops_stale_rows(bot: CazzuBot) -> None:
    await bot.scheduler.add(
        "cad", pendulum.now("UTC").subtract(seconds=1)
    )
    await bot.scheduler.arm("cad", Cadence(time="00:00"))
    assert len(await bot.scheduler.get("cad")) == 1


async def test_arm_is_idempotent(bot: CazzuBot) -> None:
    await bot.scheduler.arm("cad", Cadence(time="00:00"))
    await bot.scheduler.arm("cad", Cadence(time="00:00"))
    assert len(await bot.scheduler.get("cad")) == 1


async def test_arm_weekly(bot: CazzuBot) -> None:
    cadence = Cadence("00:00", weekday=6)
    await bot.scheduler.arm("cad", cadence)
    rows = await bot.scheduler.get("cad")
    assert len(rows) == 1
    assert _parse_dt(rows[0].run_at) == cadence.next_run(
        pendulum.now("UTC")
    )
