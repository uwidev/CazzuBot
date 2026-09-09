"""Command error translation — what the invoker sees when a command fails.

Depended on by: ``CazzuBot._on_command_error`` (core/bot.py), which
lightbulb calls for every failed command pipeline. A failure the invoker
never hears about reads as a hung command, so the silent cases are pinned
here.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import hikari
import lightbulb

from core.bot import CazzuBot
from tests.fakes import FakeContext


def _forbidden(
    message: str = "Missing Access", code: int = 50001
) -> hikari.ForbiddenError:
    """A 403 built the way hikari builds it from a Discord response."""
    return hikari.ForbiddenError(
        url="https://discord.com/api/v10/channels/1/messages",
        headers={},
        raw_body=None,
        message=message,
        code=code,
    )


def _failed(
    err: Exception, ctx: FakeContext
) -> lightbulb.exceptions.ExecutionPipelineFailedException:
    """Wrap ``err`` the way lightbulb's pipeline does for error handlers."""
    cast(Any, ctx).command_data = SimpleNamespace(
        qualified_name="story compile"
    )
    return lightbulb.exceptions.ExecutionPipelineFailedException(
        [], err, cast(Any, None), cast(Any, ctx)
    )


async def test_forbidden_error_is_reported_to_the_invoker(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    """A refused request tells the invoker instead of ending silently."""
    handled = await bot._on_command_error(  # pyright: ignore[reportPrivateUsage]
        _failed(_forbidden(), ctx)
    )

    assert handled is True
    sent = ctx.sent[-1]
    assert sent.flags & hikari.MessageFlag.EPHEMERAL
    assert "Missing Access" in str(sent.content)


async def test_unknown_error_is_left_to_lightbulb(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    """An unrecognized failure keeps lightbulb's own logging path."""
    handled = await bot._on_command_error(  # pyright: ignore[reportPrivateUsage]
        _failed(RuntimeError("boom"), ctx)
    )

    assert handled is False
    assert ctx.sent == []
