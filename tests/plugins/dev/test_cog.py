"""Dev plugin — owner gating, calc helpers, hotswap error paths."""

from __future__ import annotations

from cazzubot import levels
from cazzubot.bot import CazzuBot
from plugins.dev import DevCog, HotswapCog
from tests.fakes import FakeContext, FakeMember


def _cog(bot: CazzuBot) -> DevCog:
    cog = bot.get_cog(DevCog.__cog_name__)
    assert isinstance(cog, DevCog)
    return cog


def _hotswap(bot: CazzuBot) -> HotswapCog:
    cog = bot.get_cog(HotswapCog.__cog_name__)
    assert isinstance(cog, HotswapCog)
    return cog


async def test_owner_gate(bot: CazzuBot, ctx: FakeContext) -> None:
    assert await _cog(bot).cog_check(ctx) is False  # author != owner
    owner = FakeMember(id=1, name="owner", guild=ctx.guild)
    owner_ctx = FakeContext(
        bot=bot, author=owner, guild=ctx.guild, channel=ctx.channel
    )
    assert await _cog(bot).cog_check(owner_ctx) is True
    assert await _hotswap(bot).cog_check(owner_ctx) is True


async def test_owner_command(bot: CazzuBot, ctx: FakeContext) -> None:
    await _cog(bot).owner(ctx)
    assert ctx.sent[-1].content == f"You are {ctx.author.mention}!"


async def test_calc_helpers(bot: CazzuBot, ctx: FakeContext) -> None:
    cog = _cog(bot)
    await cog.calc_to(ctx, 5)
    assert ctx.sent[-1].content == f"{levels.exp_to_level(5):.2f}"
    await cog.calc_cum(ctx, 5)
    assert ctx.sent[-1].content == f"{levels.exp_to_level_cum(5):.2f}"


async def test_plugin_reload_rejects_unknown(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await _hotswap(bot).plugin_reload(ctx, plugin_name="nope")
    assert ctx.sent[-1].content == "❌ plugin nope is not loaded"


async def test_plugin_reload_roundtrip(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await _hotswap(bot).plugin_reload(ctx, plugin_name="counter")
    assert ctx.sent[-1].content == "✅ plugin counter has been reloaded"
    assert "counter" in [p.name for p in bot.plugins]
