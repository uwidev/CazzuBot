"""Scheduler dispatch, concurrency, retry and missed-run policies."""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any

import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.scheduler import Scheduler, Task, TaskPolicy


async def _pump(bot: CazzuBot) -> None:
    """Dispatch due rows once and wait for the handlers to finish."""
    await bot.scheduler._tick()  # pyright: ignore[reportPrivateUsage]  # pump
    await bot.scheduler._drain()  # pyright: ignore[reportPrivateUsage]  # pump


def _parse_dt(iso: str) -> pendulum.DateTime:
    """Parse a stored ISO timestamp (pendulum.parse returns a union)."""
    parsed = pendulum.parse(iso)
    assert isinstance(parsed, pendulum.DateTime)
    return parsed


async def _fail_once(bot: CazzuBot, tag: str) -> list[Task]:
    """Run one failing dispatch; return the surviving task row."""

    async def bad_handler(
        _bot: CazzuBot, _payload: dict[str, Any]
    ) -> None:
        raise RuntimeError("transient")

    bot.scheduler.register(tag, bad_handler)
    await bot.scheduler.add(
        tag, pendulum.now("UTC").subtract(seconds=1), {"retry": True}
    )
    await _pump(bot)
    return await bot.scheduler.get(tag)


# -- dispatch + cleanup ---------------------------------------------------


async def test_dispatch_and_row_cleanup(bot: CazzuBot) -> None:
    fired: list[dict[str, Any]] = []

    async def handler(_bot: CazzuBot, payload: dict[str, Any]) -> None:
        fired.append(payload)

    bot.scheduler.register("test", handler)
    await bot.scheduler.add(
        "test", pendulum.now("UTC").subtract(seconds=1), {"x": 1}
    )
    await _pump(bot)
    assert fired == [{"x": 1}]
    assert await bot.scheduler.get("test") == []


async def test_no_double_dispatch(bot: CazzuBot) -> None:
    """A row still in flight is skipped by later ticks, never re-run."""

    calls = 0

    async def counting_handler(
        _bot: CazzuBot, _payload: dict[str, Any]
    ) -> None:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.1)

    bot.scheduler.register("once", counting_handler)
    await bot.scheduler.add(
        "once", pendulum.now("UTC").subtract(seconds=1)
    )
    # second tick while the first dispatch is still running — the row is
    # still due (only deleted on success), so without the in-flight guard
    # this would fire twice
    await bot.scheduler._tick()  # pyright: ignore[reportPrivateUsage]
    await bot.scheduler._tick()  # pyright: ignore[reportPrivateUsage]
    await bot.scheduler._drain()  # pyright: ignore[reportPrivateUsage]
    assert calls == 1
    assert await bot.scheduler.get("once") == []


async def test_due_tasks_run_concurrently(bot: CazzuBot) -> None:
    """Slow handlers don't serialize each other (or the tick)."""
    started: list[float] = []
    finished: list[float] = []

    async def slow(_bot: CazzuBot, _payload: dict[str, Any]) -> None:
        started.append(time.monotonic())
        await asyncio.sleep(0.05)
        finished.append(time.monotonic())

    bot.scheduler.register("a", slow)
    bot.scheduler.register("b", slow)
    await bot.scheduler.add("a", pendulum.now("UTC").subtract(seconds=1))
    await bot.scheduler.add("b", pendulum.now("UTC").subtract(seconds=1))
    await _pump(bot)
    assert len(started) == 2 and len(finished) == 2
    # both started before either finished ⟺ they overlapped
    assert max(started) < min(finished)


async def test_concurrency_limit(bot: CazzuBot) -> None:
    """A concurrency=1 scheduler runs due rows serially, all of them."""
    active = 0
    peak = 0
    ran: list[str] = []

    async def serial_handler(
        _bot: CazzuBot, payload: dict[str, Any]
    ) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        ran.append(str(payload["n"]))
        await asyncio.sleep(0.01)
        active -= 1

    limited = Scheduler(bot, concurrency=1)
    await limited.start()
    limited.register("serial", serial_handler)
    await limited.add(
        "serial", pendulum.now("UTC").subtract(seconds=1), {"n": 1}
    )
    await limited.add(
        "serial", pendulum.now("UTC").subtract(seconds=1), {"n": 2}
    )
    await limited._tick()  # pyright: ignore[reportPrivateUsage]
    await limited._drain()  # pyright: ignore[reportPrivateUsage]
    await limited.stop()
    assert peak == 1
    assert ran == ["1", "2"]


# -- retry policy ---------------------------------------------------------


async def test_failed_task_kept_for_retry(bot: CazzuBot) -> None:
    """A retry-opted task keeps its row, pushed into the future, attempt=1."""
    rows = await _fail_once(bot, "flaky")
    assert len(rows) == 1, rows
    assert rows[0].payload["attempt"] == 1
    assert _parse_dt(rows[0].run_at) > pendulum.now("UTC")


async def test_failed_task_resolves_by_default(bot: CazzuBot) -> None:
    """Fire-and-forget default (v1): a failing handler's row still resolves."""
    calls = 0

    async def bad(_bot: CazzuBot, _payload: dict[str, Any]) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    bot.scheduler.register("resolve", bad)
    await bot.scheduler.add(
        "resolve", pendulum.now("UTC").subtract(seconds=1)
    )
    await _pump(bot)
    assert calls == 1
    assert await bot.scheduler.get("resolve") == []  # row deleted


async def test_retry_backoff_delays(bot: CazzuBot) -> None:
    """First failure uses backoff[0]; later failures escalate then repeat."""
    policy = TaskPolicy(backoff=(5, 30, 300))
    assert policy.delay_for(0) == 5
    assert policy.delay_for(1) == 30
    assert policy.delay_for(2) == 300
    assert policy.delay_for(9) == 300  # last value repeats


async def test_failed_task_uses_policy_backoff(bot: CazzuBot) -> None:
    """A custom backoff moves run_at by that delay, not the default 30s."""

    async def bad(_bot: CazzuBot, _payload: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    bot.scheduler.register(
        "slowflaky", bad, policy=TaskPolicy(backoff=(2, 60))
    )
    await bot.scheduler.add(
        "slowflaky",
        pendulum.now("UTC").subtract(seconds=1),
        {"retry": True},
    )
    await _pump(bot)
    rows = await bot.scheduler.get("slowflaky")
    assert len(rows) == 1
    delta = _parse_dt(rows[0].run_at) - pendulum.now("UTC")
    assert 1 <= delta.total_seconds() <= 3, delta


async def test_failed_task_dropped_after_max_attempts(
    bot: CazzuBot,
) -> None:
    """max_attempts caps retries; the row is dropped once exceeded."""
    attempts: list[int] = []

    async def bad(_bot: CazzuBot, _payload: dict[str, Any]) -> None:
        attempts.append(int(_payload.get("attempt", 0)))
        raise RuntimeError("boom")

    bot.scheduler.register(
        "doomed", bad, policy=TaskPolicy(max_attempts=2, backoff=(0,))
    )
    await bot.scheduler.add(
        "doomed",
        pendulum.now("UTC").subtract(seconds=1),
        {"retry": True},
    )
    for _ in range(3):
        await _pump(bot)
    assert attempts == [0, 1, 2]  # attempts seen by the handler
    assert await bot.scheduler.get("doomed") == []


async def test_attempt_count_persists_across_dispatches(
    bot: CazzuBot,
) -> None:
    """Repeated dispatches keep bumping the persisted attempt counter."""
    rows = await _fail_once(bot, "flaky2")
    assert rows[0].payload["attempt"] == 1
    # second dispatch of the same row (a real retry would come back due
    # after the backoff; force it due again here)
    await bot.scheduler.update_run_at(
        rows[0].id, pendulum.now("UTC").subtract(seconds=1)
    )
    await _pump(bot)
    rows = await bot.scheduler.get("flaky2")
    assert rows[0].payload["attempt"] == 2


# -- missed-run policy ----------------------------------------------------


async def test_due_while_down_fires_by_default(bot: CazzuBot) -> None:
    """Default policy fires a row no matter how old (backward compat)."""
    fired: list[str] = []

    async def handler(_bot: CazzuBot, _payload: dict[str, Any]) -> None:
        fired.append("ran")

    bot.scheduler.register("old", handler)
    await bot.scheduler.add(
        "old", pendulum.now("UTC").subtract(seconds=120)
    )
    await _pump(bot)
    assert fired == ["ran"]


async def test_stale_task_dropped_without_running(bot: CazzuBot) -> None:
    """stale_after is the missed-run rule: too-old rows are dropped."""
    fired: list[str] = []

    async def handler(_bot: CazzuBot, _payload: dict[str, Any]) -> None:
        fired.append("ran")

    bot.scheduler.register(
        "stale",
        handler,
        policy=TaskPolicy(stale_after=timedelta(seconds=60)),
    )
    await bot.scheduler.add(
        "stale", pendulum.now("UTC").subtract(seconds=120)
    )
    await _pump(bot)
    assert fired == []
    assert await bot.scheduler.get("stale") == []


async def test_freshly_due_task_not_stale(bot: CazzuBot) -> None:
    """A row inside the stale window still runs."""
    fired: list[str] = []

    async def handler(_bot: CazzuBot, _payload: dict[str, Any]) -> None:
        fired.append("ran")

    bot.scheduler.register(
        "fresh",
        handler,
        policy=TaskPolicy(stale_after=timedelta(seconds=60)),
    )
    await bot.scheduler.add(
        "fresh", pendulum.now("UTC").subtract(seconds=5)
    )
    await _pump(bot)
    assert fired == ["ran"]
