"""Scheduler dispatch + retry — ported from scripts/functest.py."""

from __future__ import annotations

from typing import Any

import pendulum

from cazzubot.bot import CazzuBot


async def test_dispatch_and_row_cleanup(bot: CazzuBot) -> None:
    fired: list[dict[str, Any]] = []

    async def handler(_bot: CazzuBot, payload: dict[str, Any]) -> None:
        fired.append(payload)

    bot.scheduler.register("test", handler)
    await bot.scheduler.add(
        "test", pendulum.now("UTC").subtract(seconds=1), {"x": 1}
    )
    await bot.scheduler._tick()  # pyright: ignore[reportPrivateUsage]  # pump
    assert fired == [{"x": 1}]
    assert await bot.scheduler.get("test") == []


async def test_failed_task_kept_for_retry(bot: CazzuBot) -> None:
    """A failing handler keeps its row, pushed 30s into the future."""

    async def bad_handler(
        _bot: CazzuBot, _payload: dict[str, Any]
    ) -> None:
        raise RuntimeError("transient")

    bot.scheduler.register("flaky", bad_handler)
    await bot.scheduler.add(
        "flaky", pendulum.now("UTC").subtract(seconds=1)
    )
    await bot.scheduler._tick()  # pyright: ignore[reportPrivateUsage]  # pump
    rows = await bot.scheduler.get("flaky")
    assert len(rows) == 1, rows
