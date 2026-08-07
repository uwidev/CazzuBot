"""CommandWindow buffered reporting — ported from scripts/functest.py."""

from __future__ import annotations

import pytest

from cazzubot.window import (
    command_window,
    window_info,
    window_warn,
    windowed,
)
from tests.fakes import FakeContext, SentMessage


async def test_window_buffers_levels_into_one_message(
    ctx: FakeContext,
) -> None:
    async with command_window(ctx) as window:
        window.debug("dbg")
        window.info("fetching")
        window.success("done")
        window.warn("slow")
        window.error("boom")
    assert len(ctx.sent) == 1  # one message, not one per line
    sent = ctx.sent[0]
    assert sent.content is not None
    lines = sent.content.splitlines()
    assert lines[0] == "dbg"
    assert lines[2] == "✓ done"
    assert lines[3] == "⚠︎ slow"
    assert lines[4] == "✖ boom"
    assert sent.ephemeral is True


async def test_window_empty_flush_is_a_noop(ctx: FakeContext) -> None:
    async with command_window(ctx) as _window:
        pass
    assert ctx.sent == []


async def test_window_flushes_state_and_error_on_exception(
    ctx: FakeContext,
) -> None:
    with pytest.raises(RuntimeError):
        async with command_window(ctx) as window:
            window.info("partial")
            raise RuntimeError("kaboom")
    sent = ctx.sent[0]
    assert sent.content is not None
    assert (
        "partial" in sent.content
        and "✖ RuntimeError: kaboom" in sent.content
    )


async def test_window_monospace_flush(ctx: FakeContext) -> None:
    async with command_window(ctx) as window:
        window.info("a|b")
        await window.flush(monospace=True)
    assert ctx.sent[0].content == "```\na|b\n```"


async def test_windowed_decorator_exposes_window_and_autoflushes(
    ctx: FakeContext,
) -> None:
    @windowed
    async def _cmd(_self: object, c: FakeContext, val: int) -> int:
        c.window.success(f"val={val}")
        return val

    assert await _cmd(None, ctx, 3) == 3
    assert ctx.sent == [SentMessage(content="✓ val=3", ephemeral=True)]


async def test_window_one_offs(ctx: FakeContext) -> None:
    await window_info(ctx, "hi")
    await window_warn(ctx, "careful")
    assert len(ctx.sent) == 2
    assert ctx.sent[0].content == "hi"
    assert ctx.sent[1].content == "⚠︎ careful"
