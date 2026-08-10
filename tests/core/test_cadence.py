"""At/In — next/previous run math, the missed rule, and the chaotic flavors."""

from __future__ import annotations

import pendulum
import pytest

from cazzubot.scheduler import At, AtChaotic, In, InChaotic

# 2026-08-10 is a Monday; 2026-08-16 is the following Sunday.
# pendulum weekday(): Monday=0 … Sunday=6.


def _dt(
    *, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> pendulum.DateTime:
    """An instant in the fixed test week (August 2026, UTC)."""
    return pendulum.datetime(2026, 8, day, hour, minute, second, tz="UTC")


# -- next_run -------------------------------------------------------------


async def test_daily_next_run_later_today() -> None:
    assert At("22:00").next_run(_dt(day=10, hour=13, minute=30)) == (
        _dt(day=10, hour=22)
    )


async def test_daily_next_run_tomorrow_after_time() -> None:
    assert At("09:00").next_run(_dt(day=10, hour=13)) == _dt(
        day=11, hour=9
    )


async def test_daily_next_run_at_the_instant_rolls_to_tomorrow() -> None:
    """next_run is strictly future — arming at exactly 09:00 goes to day 2."""
    assert At("09:00").next_run(_dt(day=10, hour=9)) == _dt(day=11, hour=9)


async def test_daily_next_run_midnight() -> None:
    assert At("00:00").next_run(_dt(day=10, hour=23, minute=59)) == (
        _dt(day=11)
    )


async def test_weekly_next_run_rolls_forward_to_target_day() -> None:
    """Wednesday → next Monday."""
    assert At("09:00", weekday=0).next_run(_dt(day=12, hour=13)) == _dt(
        day=17, hour=9
    )


async def test_weekly_next_run_same_day_before_time() -> None:
    assert At("09:00", weekday=0).next_run(_dt(day=10, hour=8)) == _dt(
        day=10, hour=9
    )


async def test_weekly_next_run_same_day_after_time_rolls_a_week() -> None:
    assert At("09:00", weekday=0).next_run(_dt(day=10, hour=10)) == _dt(
        day=17, hour=9
    )


async def test_weekly_next_run_sunday_wrap() -> None:
    """Friday and Monday both land on the coming Sunday 00:00."""
    sunday = _dt(day=16)
    assert At("00:00", weekday=6).next_run(_dt(day=14, hour=12)) == sunday
    assert At("00:00", weekday=6).next_run(_dt(day=10, hour=12)) == sunday


# -- previous_run ---------------------------------------------------------


async def test_previous_run_daily_earlier_today() -> None:
    assert At("09:00").previous_run(_dt(day=10, hour=13)) == (
        _dt(day=10, hour=9)
    )


async def test_previous_run_daily_yesterday_after_time() -> None:
    assert At("22:00").previous_run(_dt(day=10, hour=13)) == (
        _dt(day=9, hour=22)
    )


async def test_previous_run_weekly_this_week() -> None:
    """Wednesday → this week's Monday."""
    assert At("09:00", weekday=0).previous_run(
        _dt(day=12, hour=13)
    ) == _dt(day=10, hour=9)


async def test_previous_run_weekly_before_time_on_target_day() -> None:
    """Monday 08:00 → last week's Monday (today's 09:00 hasn't happened)."""
    assert At("09:00", weekday=0).previous_run(_dt(day=10, hour=8)) == _dt(
        day=3, hour=9
    )


async def test_previous_run_weekly_wrap_to_last_week() -> None:
    """Monday → the previous Sunday."""
    assert At("00:00", weekday=6).previous_run(
        _dt(day=10, hour=12)
    ) == _dt(day=9)


# -- missed (the catch-up rule) --------------------------------------------


async def test_missed_true_when_last_run_predates_occurrence() -> None:
    """Last reset yesterday 20:00 — today's midnight never ran."""
    assert At("00:00").missed(_dt(day=9, hour=20), _dt(day=10, hour=10))


async def test_missed_false_when_occurrence_serviced() -> None:
    assert not At("00:00").missed(
        _dt(day=10, hour=0), _dt(day=10, hour=10)
    )


async def test_missed_false_after_late_reset() -> None:
    """A reset after the occurrence (00:05) still covers it."""
    assert not At("00:00").missed(
        _dt(day=10, hour=0, minute=5), _dt(day=10, hour=10)
    )


async def test_missed_weekly() -> None:
    """Last Sunday ran, this Sunday's 00:00 hasn't — missed."""
    cadence = At("00:00", weekday=6)
    assert cadence.missed(_dt(day=9, hour=0), _dt(day=16, hour=10))
    assert not cadence.missed(_dt(day=16, hour=0), _dt(day=16, hour=10))


# -- validation ------------------------------------------------------------


async def test_cadence_validation() -> None:
    for bad in ("25:00", "9:00", "ab:cd", "00:60", ""):
        with pytest.raises(ValueError):
            At(time=bad)
    for bad_weekday in (-1, 7):
        with pytest.raises(ValueError):
            At(time="00:00", weekday=bad_weekday)
    # valid forms
    At(time="00:00")
    At(time="23:59", weekday=6)


# -- InChaotic (relative chaos) --------------------------------------------


async def test_inchaotic_jitter_zero_is_exact() -> None:
    assert InChaotic(interval=120).next_run(_dt(day=10, hour=13)) == _dt(
        day=10, hour=13, minute=2
    )


async def test_inchaotic_rolls_inside_bounds() -> None:
    """Seeded rolls always land inside the ±jitter window."""
    cadence = InChaotic(interval=300, jitter=0.5, seed=42)
    now = _dt(day=10, hour=13)
    earliest, latest = cadence.bounds(now)
    for _ in range(50):
        run = cadence.next_run(now)
        assert earliest <= run <= latest


async def test_inchaotic_seed_determinism() -> None:
    """Equal specs with equal seeds roll identically."""
    now = _dt(day=10, hour=13)
    a = InChaotic(interval=300, jitter=0.5, seed=7)
    b = InChaotic(interval=300, jitter=0.5, seed=7)
    for _ in range(10):
        assert a.next_run(now) == b.next_run(now)


async def test_inchaotic_bounds_are_exact() -> None:
    assert InChaotic(interval=300, jitter=0.5).bounds(
        _dt(day=10, hour=13)
    ) == (
        _dt(day=10, hour=13, minute=2, second=30),
        _dt(day=10, hour=13, minute=7, second=30),
    )


async def test_inchaotic_validation() -> None:
    for bad_interval in (0, -5):
        with pytest.raises(ValueError):
            InChaotic(interval=bad_interval)
    for bad_jitter in (-0.1, 1.5):
        with pytest.raises(ValueError):
            InChaotic(interval=60, jitter=bad_jitter)


# -- monthly / quarterly (day-of-month family) -----------------------------


def _mdt(
    year: int = 2026,
    month: int = 1,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
) -> pendulum.DateTime:
    """An instant in 2026 by default (2028 for leap-February cases)."""
    return pendulum.datetime(year, month, day, hour, minute, tz="UTC")


async def test_monthly_next_run() -> None:
    cadence = At(day=1, time="00:00")
    assert cadence.next_run(_mdt(month=2, day=15)) == _mdt(month=3, day=1)
    # at the instant itself → strictly future, next month
    assert cadence.next_run(_mdt(month=1, day=1)) == _mdt(month=2, day=1)
    # year wrap
    assert cadence.next_run(_mdt(month=12, day=31, hour=23)) == (
        _mdt(year=2027, month=1, day=1)
    )


async def test_monthly_skips_short_months() -> None:
    """Cron skip semantics: a month lacking the day has no occurrence."""
    cadence = At(day=31, time="09:00")
    assert cadence.next_run(_mdt(month=1, day=15)) == _mdt(
        month=1, day=31, hour=9
    )
    assert cadence.next_run(_mdt(month=2, day=15)) == _mdt(
        month=3, day=31, hour=9
    )  # Feb skipped
    # after December's occurrence → year wrap
    assert cadence.next_run(_mdt(month=12, day=31, hour=10)) == _mdt(
        year=2027, month=1, day=31, hour=9
    )


async def test_monthly_next_run_leap_feb() -> None:
    cadence = At(day=29, time="00:00")
    assert cadence.next_run(_mdt(year=2028, month=2, day=15)) == (
        _mdt(year=2028, month=2, day=29)
    )  # 2028 is a leap year
    # Feb-only day=29: the next leap Feb 29 (2029-2031 lack it)
    feb_only = At(day=29, months=(2,), time="00:00")
    assert feb_only.next_run(_mdt(year=2027, month=3, day=1)) == (
        _mdt(year=2028, month=2, day=29)
    )
    assert feb_only.next_run(_mdt(year=2028, month=3, day=1)) == (
        _mdt(year=2032, month=2, day=29)
    )  # 4-year scan


async def test_quarterly_next_run() -> None:
    cadence = At(day=1, months=(1, 4, 7, 10), time="00:00")
    assert cadence.next_run(_mdt(month=2, day=15)) == _mdt(month=4, day=1)
    # at the boundary itself → strictly future, next quarter
    assert cadence.next_run(_mdt(month=4, day=1)) == _mdt(month=7, day=1)
    # year wrap
    assert cadence.next_run(_mdt(month=10, day=2)) == _mdt(
        year=2027, month=1, day=1
    )


async def test_previous_run_monthly() -> None:
    cadence = At(day=31, time="00:00")
    assert cadence.previous_run(_mdt(month=3, day=15)) == (
        _mdt(month=1, day=31)
    )  # Feb skipped
    assert cadence.previous_run(_mdt(month=1, day=31)) == (
        _mdt(month=1, day=31)
    )  # at-or-before


async def test_previous_run_quarterly() -> None:
    cadence = At(day=1, months=(1, 4, 7, 10), time="00:00")
    assert cadence.previous_run(_mdt(month=5, day=15)) == _mdt(
        month=4, day=1
    )
    assert cadence.previous_run(_mdt(month=1, day=15)) == _mdt(
        month=1, day=1
    )
    assert cadence.previous_run(_mdt(month=1, day=1)) == _mdt(
        month=1, day=1
    )


async def test_missed_quarterly() -> None:
    cadence = At(day=1, months=(1, 4, 7, 10), time="00:00")
    # bot down over the Apr 1 boundary: last freeze predates it
    assert cadence.missed(_mdt(month=3, day=31), _mdt(month=5, day=15))
    # serviced: last freeze at the boundary itself
    assert not cadence.missed(_mdt(month=4, day=1), _mdt(month=5, day=15))


async def test_cadence_validation_monthly() -> None:
    with pytest.raises(ValueError):
        At(time="00:00", weekday=0, day=1)  # both selectors
    with pytest.raises(ValueError):
        At(time="00:00", months=(1,))  # months without day
    with pytest.raises(ValueError):
        At(time="00:00", months=())  # empty months
    for bad_day in (0, 32):
        with pytest.raises(ValueError):
            At(time="00:00", day=bad_day)
    for bad_month in (0, 13):
        with pytest.raises(ValueError):
            At(time="00:00", day=1, months=(bad_month,))
    with pytest.raises(ValueError):
        At(time="00:00", day=30, months=(2,))  # Feb never has 30
    # valid: Feb-only day=29 (leap years) and the quarterly rollover
    At(time="00:00", day=29, months=(2,))
    At(time="00:00", day=1, months=(1, 4, 7, 10))


async def test_last_day_of_month() -> None:
    """day=-1 is the last day — Feb included, leap years honored."""
    cadence = At(day=-1, time="00:00")
    assert cadence.next_run(_mdt(month=1, day=15)) == _mdt(month=1, day=31)
    assert cadence.next_run(_mdt(month=2, day=15)) == _mdt(
        month=2, day=28
    )  # 2026 is not a leap year
    assert cadence.next_run(_mdt(month=2, day=28, hour=10)) == (
        _mdt(month=3, day=31)
    )
    assert cadence.next_run(_mdt(year=2028, month=2, day=15)) == (
        _mdt(year=2028, month=2, day=29)
    )  # leap year
    assert cadence.previous_run(_mdt(month=3, day=15)) == (
        _mdt(month=2, day=28)
    )


async def test_second_to_last_day() -> None:
    cadence = At(day=-2, time="00:00")
    assert cadence.next_run(_mdt(month=1, day=15)) == _mdt(month=1, day=30)
    assert cadence.next_run(_mdt(month=2, day=15)) == _mdt(month=2, day=27)


async def test_last_day_of_quarter() -> None:
    cadence = At(day=-1, months=(1, 4, 7, 10), time="00:00")
    assert cadence.next_run(_mdt(month=2, day=15)) == _mdt(month=4, day=30)
    assert cadence.next_run(_mdt(month=4, day=30, hour=10)) == (
        _mdt(month=7, day=31)
    )


async def test_cadence_validation_negative_day() -> None:
    for bad_day in (0, 32, -32):
        with pytest.raises(ValueError):
            At(time="00:00", day=bad_day)
    with pytest.raises(ValueError):
        At(time="00:00", day=-31, months=(2,))  # Feb never has 31
    # valid: the last day of every month, and Feb-only -29 (leap years)
    At(time="00:00", day=-1)
    At(time="00:00", day=-29, months=(2,))


async def test_in_duration_mode() -> None:
    """A relative schedule: next/previous/missed are anchored to now."""
    cadence = In(interval=120)
    now = _dt(day=10, hour=13)
    assert cadence.next_run(now) == now.add(seconds=120)
    assert cadence.previous_run(now) == now.subtract(seconds=120)
    # missed is relative: the last run older than the interval
    assert not cadence.missed(now.subtract(seconds=60), now)
    assert cadence.missed(now.subtract(seconds=300), now)


async def test_in_validation() -> None:
    for bad_interval in (0, -60):
        with pytest.raises(ValueError):
            In(interval=bad_interval)
    In(interval=120)  # valid


async def test_in_duration_string() -> None:
    """A duration string is the declaration, parsed to seconds."""
    now = _dt(day=10, hour=13)
    assert In(interval="2h").next_run(now) == now.add(seconds=7200)
    assert In(interval="90m").previous_run(now) == now.subtract(
        seconds=5400
    )
    # chaotic relative mode accepts strings too
    chaotic = InChaotic(interval="90m", jitter=0.5, seed=1)
    earliest, latest = chaotic.bounds(now)
    assert earliest == now.add(seconds=2700)
    assert latest == now.add(seconds=8100)
    for bad in ("banana", "0s"):
        with pytest.raises(ValueError):
            In(interval=bad)


async def test_weekly_multiple_days() -> None:
    """weekday can list several days; the soonest occurrence wins."""
    cadence = At(weekday=(0, 5), time="09:00")  # Monday + Saturday
    # Wednesday → the coming Saturday
    assert cadence.next_run(_dt(day=12, hour=10)) == _dt(day=15, hour=9)
    # Saturday before 09:00 → today; after 09:00 → Monday (sooner than
    # next Saturday)
    assert cadence.next_run(_dt(day=15, hour=8)) == _dt(day=15, hour=9)
    assert cadence.next_run(_dt(day=15, hour=10)) == _dt(day=17, hour=9)
    # previous: Monday afternoon → Monday's occurrence earlier that day
    assert cadence.previous_run(_dt(day=17, hour=12)) == _dt(
        day=17, hour=9
    )


async def test_weekly_validation() -> None:
    with pytest.raises(ValueError):
        At(time="00:00", weekday=())  # empty
    with pytest.raises(ValueError):
        At(time="00:00", weekday=(0, 7))  # out of range
    At(time="00:00", weekday=(0, 6))  # valid


async def test_monthly_multiple_days() -> None:
    """day can list several days of the month; the soonest wins."""
    cadence = At(day=(15, -1), time="00:00")
    assert cadence.next_run(_mdt(month=1, day=10)) == _mdt(month=1, day=15)
    assert cadence.next_run(_mdt(month=1, day=16)) == _mdt(month=1, day=31)
    # 2026: February has 28 days, so the last day is the 28th
    assert cadence.next_run(_mdt(month=2, day=20)) == _mdt(month=2, day=28)
    assert cadence.next_run(_mdt(month=2, day=28, hour=10)) == (
        _mdt(month=3, day=15)
    )
    # most recent occurrence at-or-before Feb 20 is Feb 15
    assert cadence.previous_run(_mdt(month=2, day=20)) == _mdt(
        month=2, day=15
    )


async def test_monthly_multiple_days_with_months() -> None:
    """Day lists compose with month eligibility."""
    cadence = At(day=(15, -1), months=(1, 4, 7, 10), time="00:00")
    assert cadence.next_run(_mdt(month=1, day=16)) == _mdt(month=1, day=31)
    assert cadence.next_run(_mdt(month=2, day=15)) == _mdt(month=4, day=15)
    # April has 30 days, so the last day is the 30th
    assert cadence.previous_run(_mdt(month=5, day=1)) == _mdt(
        month=4, day=30
    )


async def test_monthly_validation_day_list() -> None:
    with pytest.raises(ValueError):
        At(time="00:00", day=())
    with pytest.raises(ValueError):
        At(time="00:00", day=(0, 15))
    with pytest.raises(ValueError):
        At(time="00:00", day=(32, -1))
    with pytest.raises(ValueError):
        At(time="00:00", day=(-31, -30), months=(2,))  # Feb lacks both
    At(time="00:00", day=(15, -1))  # valid


async def test_chaotic_is_a_schedule() -> None:
    """Each chaotic flavor inherits its family's declaration surface."""
    at_chaotic = AtChaotic(weekday=6, time="00:00")
    assert isinstance(at_chaotic, At)
    in_chaotic = InChaotic(interval=120)
    assert isinstance(in_chaotic, In)
    # inherited previous_run/missed work (relative for In)
    now = _dt(day=10, hour=13)
    assert in_chaotic.previous_run(now) == now.subtract(seconds=120)
    assert in_chaotic.missed(now.subtract(seconds=300), now)


async def test_chatoc_calendar_mode_stays_in_period() -> None:
    """Calendar chaos drifts forward within the period, never past it."""
    cadence = AtChaotic(weekday=6, time="00:00", jitter=0.5, seed=42)
    now = _dt(day=10, hour=13)  # Monday
    earliest, latest = cadence.bounds(now)
    assert earliest == _dt(day=16)  # the occurrence itself (Sunday)
    assert latest == _dt(day=16).add(
        days=3, hours=12
    )  # + jitter of the week
    for _ in range(50):
        run = cadence.next_run(now)
        assert earliest <= run <= latest
    # jitter=0 is the exact calendar occurrence
    plain = AtChaotic(weekday=6, time="00:00")
    assert plain.next_run(now) == _dt(day=16)
