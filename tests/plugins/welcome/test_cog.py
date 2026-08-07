"""Welcome cog tests — on_member_update flows + config commands.

The ``_send_welcome`` path sleeps 1s (production "let the UI update" delay)
and sends through the channel recorder. ``before``/``after`` are two
FakeMembers with the same id (Discord's before/after states of one member).
"""

from __future__ import annotations

import pytest
from discord.ext import commands

from cazzubot.bot import CazzuBot
from cazzubot.models import WelcomeModeEnum
from plugins.welcome import WelcomeCog
from tests.fakes import (
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeMember,
    FakeRole,
)

_MSG = {"content": "hi {mention}"}


def _cog(bot: CazzuBot) -> WelcomeCog:
    cog = bot.get_cog(WelcomeCog.__cog_name__)
    assert isinstance(cog, WelcomeCog)
    return cog


def _member(
    guild: FakeGuild,
    id: int,
    *,
    pending: bool = False,
    roles: list[FakeRole] | None = None,
) -> FakeMember:
    member = FakeMember(id=id, name=f"user{id}", guild=guild, roles=roles)
    member.pending = pending
    guild.add_member(member)
    return member


async def _configure(
    bot: CazzuBot,
    *,
    cid: int = 99,
    mode: str = WelcomeModeEnum.PENDING.value,
    default_rid: int | None = None,
    monitor_rid: int | None = None,
) -> None:
    await bot.settings.set("welcome.enabled", True)
    await bot.settings.set("welcome.cid", cid)
    await bot.settings.set("welcome.message", _MSG)
    await bot.settings.set("welcome.mode", mode)
    if default_rid is not None:
        await bot.settings.set("welcome.default_rid", default_rid)
    if monitor_rid is not None:
        await bot.settings.set("welcome.monitor_rid", monitor_rid)


async def test_pending_mode_welcomes_and_adds_role(
    bot: CazzuBot, fake_guild: FakeGuild, channel: FakeChannel
) -> None:
    role = FakeRole(id=300, name="Member")
    fake_guild.add_role(role)
    await _configure(bot, default_rid=role.id)
    before = _member(fake_guild, 424242, pending=True)
    after = _member(fake_guild, 424242, pending=False)

    await _cog(bot).on_member_update(before, after)

    assert channel.sent[-1]["content"] == "hi <@424242>"
    assert role in after.added_roles


async def test_disabled_skips_welcome(
    bot: CazzuBot, fake_guild: FakeGuild, channel: FakeChannel
) -> None:
    before = _member(fake_guild, 424242, pending=True)
    after = _member(fake_guild, 424242, pending=False)
    await _cog(bot).on_member_update(before, after)
    assert channel.sent == []


async def test_last_welcomed_guard_prevents_double(
    bot: CazzuBot, fake_guild: FakeGuild, channel: FakeChannel
) -> None:
    await _configure(bot)
    before = _member(fake_guild, 424242, pending=True)
    after = _member(fake_guild, 424242, pending=False)
    cog = _cog(bot)

    await cog.on_member_update(before, after)
    await cog.on_member_update(before, after)  # same id again

    assert len(channel.sent) == 1


async def test_role_mode_welcomes_on_monitored_role(
    bot: CazzuBot, fake_guild: FakeGuild, channel: FakeChannel
) -> None:
    monitor = FakeRole(id=500, name="Verified")
    fake_guild.add_role(monitor)
    await _configure(bot, mode="role", monitor_rid=monitor.id)
    before = _member(fake_guild, 424242)
    after = _member(fake_guild, 424242, roles=[monitor])

    await _cog(bot).on_member_update(before, after)

    assert channel.sent[-1]["content"] == "hi <@424242>"


async def test_role_mode_ignores_other_roles(
    bot: CazzuBot, fake_guild: FakeGuild, channel: FakeChannel
) -> None:
    other = FakeRole(id=501, name="Other")
    fake_guild.add_role(other)
    await _configure(bot, mode="role", monitor_rid=500)
    before = _member(fake_guild, 424242)
    after = _member(fake_guild, 424242, roles=[other])

    await _cog(bot).on_member_update(before, after)

    assert channel.sent == []


# -- config commands -------------------------------------------------------


async def test_config_commands_roundtrip(
    bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    role = FakeRole(id=300, name="Member")
    cog = _cog(bot)
    await cog.welcome_set_enabled(ctx, True)
    assert await bot.settings.get("welcome.enabled") is True
    await cog.welcome_set_cid(ctx, channel)
    assert await bot.settings.get("welcome.cid") == 99
    await cog.welcome_set_rid(ctx, role)
    assert await bot.settings.get("welcome.default_rid") == 300
    await cog.welcome_set_mode(ctx, mode="role")
    assert await bot.settings.get("welcome.mode") == "role"
    assert ctx.sent[-1].content == "✓ Welcome mode set to role"


async def test_welcome_set_mode_rejects_invalid(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(commands.BadArgument):
        await _cog(bot).welcome_set_mode(ctx, mode="bogus")


async def test_welcome_set_message_verifies_and_stores(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await _cog(bot).welcome_set_message(
        ctx, message='{"content": "hi {mention}"}'
    )
    stored = await bot.settings.get("welcome.message")
    assert stored is not None and stored["content"] == "hi {mention}"
    with pytest.raises(commands.BadArgument):
        await _cog(bot).welcome_set_message(ctx, message='{"content": 42}')


async def test_welcome_demo_and_raw(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    cog = _cog(bot)
    await cog.welcome_demo(ctx)
    assert ctx.sent[-1].content == "No welcome message has been set."
    await cog.welcome_raw(ctx)
    assert ctx.sent[-1].content is not None
    assert "null" in ctx.sent[-1].content  # json.dumps(None)
