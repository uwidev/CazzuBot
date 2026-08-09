# pyright: reportArgumentType=false
"""Dev plugin — owner gating, calc helpers, hotswap error paths."""

from __future__ import annotations

import pytest
from lightbulb.prefab.checks import NotOwner, owner_only

from cazzubot import levels
from cazzubot.bot import CazzuBot
from plugins.dev.cog import (
    CalcCum,
    CalcTo,
    Owner,
    PluginReload,
)
from tests.fakes import (
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeMember,
    invoke_command,
)


async def test_owner_gate(
    bot: CazzuBot,
    ctx: FakeContext,
    fake_guild: FakeGuild,
    channel: FakeChannel,
) -> None:
    ctx.client._owner_ids = {1}  # no _ensure_application network call
    with pytest.raises(NotOwner):
        await owner_only(None, ctx)  # author 424242 != owner

    owner = FakeMember(id=1, name="owner")
    owner_ctx = FakeContext(
        bot=bot,
        member=owner,
        guild=fake_guild,
        channel=channel,
    )
    owner_ctx.client._owner_ids = {1}
    await owner_only(None, owner_ctx)  # no raise


async def test_owner_command(bot: CazzuBot, ctx: FakeContext) -> None:
    await invoke_command(Owner(), ctx)
    assert ctx.sent[-1].content == f"You are {ctx.member.mention}!"


async def test_calc_helpers(bot: CazzuBot, ctx: FakeContext) -> None:
    await invoke_command(CalcTo(), ctx, n=5)
    assert ctx.sent[-1].content == f"{levels.exp_for_level(5):.2f}"
    await invoke_command(CalcCum(), ctx, n=5)
    assert ctx.sent[-1].content == f"{levels.exp_to_level_cum(5):.2f}"


async def test_plugin_reload_rejects_unknown(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await invoke_command(PluginReload(), ctx, plugin_name="nope")
    assert ctx.sent[-1].content == "❌ plugin nope is not loaded"


async def test_plugin_reload_roundtrip(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    bot.plugins_dir = "plugins"  # the fixture boots an empty temp dir
    await bot.load_plugin_by_name("counter")
    assert "counter" in [p.name for p in bot.plugins]

    await invoke_command(PluginReload(), ctx, plugin_name="counter")
    assert ctx.sent[-1].content == "✅ plugin counter has been reloaded"
    assert "counter" in [p.name for p in bot.plugins]
