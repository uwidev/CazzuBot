"""Core event bus — typed handlers, ordered dispatch, failure isolation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from cazzubot.events import EventBus


@dataclass(frozen=True)
class _A:
    value: int


@dataclass(frozen=True)
class _Sub(_A):
    pass


@dataclass(frozen=True)
class _B:
    value: int


async def test_dispatch_matching_handlers_in_order() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def first(event: _A) -> None:
        seen.append(f"first:{event.value}")

    async def second(event: _A) -> None:
        seen.append(f"second:{event.value}")

    bus.on(_A, first)
    bus.on(_A, second)
    await bus.emit(_A(value=7))

    assert seen == ["first:7", "second:7"]


async def test_subclasses_match_and_unrelated_skip() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def on_a(event: _A) -> None:
        seen.append(f"a:{event.value}")

    async def on_b(event: _B) -> None:
        seen.append(f"b:{event.value}")

    bus.on(_A, on_a)
    bus.on(_B, on_b)

    await bus.emit(_Sub(value=1))  # matches the _A handler (subclass)
    await bus.emit(_B(value=2))

    assert seen == ["a:1", "b:2"]


async def test_handler_failure_is_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing observer neither breaks emit nor later handlers."""
    bus = EventBus()
    seen: list[str] = []

    async def boom(_event: _A) -> None:
        raise RuntimeError("observer failed")

    async def after(_event: _A) -> None:
        seen.append("after")

    bus.on(_A, boom)
    bus.on(_A, after)

    with caplog.at_level(logging.ERROR, logger="cazzubot.events"):
        await bus.emit(_A(value=1))

    assert seen == ["after"]  # later handlers still ran
    assert any("failed" in record.message for record in caplog.records)


async def test_no_handlers_is_a_noop() -> None:
    bus = EventBus()
    await bus.emit(_A(value=1))  # must not raise


async def test_off_removes_only_the_matching_handler() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def keep(event: _A) -> None:
        seen.append(f"keep:{event.value}")

    async def drop(event: _A) -> None:
        seen.append(f"drop:{event.value}")

    bus.on(_A, keep)
    bus.on(_A, drop)
    bus.off(_A, drop)

    await bus.emit(_A(value=1))

    assert seen == ["keep:1"]


async def test_on_returns_unsubscribe_token() -> None:
    """The token is the lifecycle-friendly inverse of ``on``."""
    bus = EventBus()
    seen: list[str] = []

    async def handler(event: _A) -> None:
        seen.append(str(event.value))

    unsubscribe = bus.on(_A, handler)
    await bus.emit(_A(value=1))
    assert seen == ["1"]

    unsubscribe()
    await bus.emit(_A(value=2))
    assert seen == ["1"]  # nothing more arrived


async def test_off_with_no_matching_handler_is_a_noop() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def handler(event: _A) -> None:
        seen.append(str(event.value))

    bus.on(_A, handler)

    async def noop(_event: _B) -> None:
        pass

    bus.off(_B, noop)  # wrong type — nothing to remove
    await bus.emit(_A(value=1))
    assert seen == ["1"]
