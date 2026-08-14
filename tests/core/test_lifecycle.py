"""Plugin lifecycle — deferred undos replayed in reverse on withdraw."""

from __future__ import annotations

from typing import Any, cast


from cazzubot.lifecycle import Lifecycle


def _lifecycle() -> Lifecycle:
    # the service stores the bot but never calls it in these paths
    return Lifecycle(cast(Any, None))


async def test_withdraw_replays_undos_in_reverse_order() -> None:
    lc = _lifecycle()
    order: list[str] = []

    lc.defer("p", lambda: order.append("first"))
    lc.defer("p", lambda: order.append("second"))
    lc.defer("p", lambda: order.append("third"))

    failures = await lc.withdraw("p")

    assert failures == []
    assert order == ["third", "second", "first"]  # reverse of application
    assert lc.pending("p") == 0


async def test_withdraw_awaits_async_undos() -> None:
    lc = _lifecycle()
    done: list[str] = []

    async def slow() -> None:
        done.append("async")

    lc.defer("p", slow)
    lc.defer("p", lambda: done.append("sync"))

    await lc.withdraw("p")

    assert done == ["sync", "async"]


async def test_failed_undo_is_isolated_and_reported() -> None:
    lc = _lifecycle()
    done: list[str] = []

    def boom() -> None:
        raise RuntimeError("undo failed")

    lc.defer("p", lambda: done.append("before"))
    lc.defer("p", boom)
    lc.defer("p", lambda: done.append("after"))

    failures = await lc.withdraw("p")

    # the cascade continues past the failure; the failure is returned
    assert done == ["after", "before"]
    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)
    assert lc.pending("p") == 0


async def test_undos_are_scoped_per_plugin() -> None:
    lc = _lifecycle()
    lc.defer("a", lambda: None)
    lc.defer("b", lambda: None)

    await lc.withdraw("a")

    assert lc.pending("a") == 0
    assert lc.pending("b") == 1
