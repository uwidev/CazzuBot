# pyright: reportArgumentType=false
"""Welcome extension tests — on_member_update flows + config commands.

The ``_send_welcome`` path sleeps 1s (production "let the UI update" delay);
the autouse fixture stubs the sleep out. ``old``/``member`` are two
FakeMembers with the same id (Discord's before/after states of one member).
"""

from __future__ import annotations

import pytest

from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.models import WelcomeModeEnum
from plugins.welcome import cog as welcome_cog
from plugins.welcome.cog import (
    Demo,
    Raw,
    SetChannel,
    SetEnabled,
    SetMessage,
    SetMode,
    SetRole,
    on_member_update,
)
from tests.fakes import (
    rest_of,
    FakeCache,
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeMember,
    FakeMemberUpdateEvent,
    FakeRole,
    invoke_command,
)

_MSG = {"content": "hi {mention}"}


@pytest.fixture(autouse=True)
def _no_send_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the 1s production UI-update sleep."""

    async def _noop(*_args: object, **_kwargs: object) -> None:
        pass

    monkeypatch.setattr(welcome_cog.asyncio, "sleep", _noop)


def _member(
    guild: FakeGuild,
    id: int,
    *,
    pending: bool = False,
    roles: list[FakeRole] | None = None,
) -> FakeMember:
    member = FakeMember(id=id, name=f"user{id}", guild=guild, roles=roles)
    member.is_pending = pending
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


async def _fire(
    seeded_bot: CazzuBot,
    old: FakeMember,
    member: FakeMember,
    fake_cache: FakeCache,
) -> None:
    fake_cache.add_member(member)
    await on_member_update(
        FakeMemberUpdateEvent(
            member=member,
            old_member=old,
            guild_id=2,
            app=seeded_bot,
        )
    )


async def test_pending_mode_welcomes_and_adds_role(
    seeded_bot: CazzuBot,
    fake_guild: FakeGuild,
    channel: FakeChannel,
    fake_cache: FakeCache,
) -> None:
    role = FakeRole(id=300, name="Member")
    fake_cache.add_role(role)
    await _configure(seeded_bot, default_rid=role.id)
    before = _member(fake_guild, 424242, pending=True)
    after = _member(fake_guild, 424242, pending=False)

    await _fire(seeded_bot, before, after, fake_cache)

    assert channel.sent[-1]["content"] == "hi <@424242>"
    assert rest_of(seeded_bot).added_roles == [(424242, role.id, None)]


async def test_disabled_skips_welcome(
    seeded_bot: CazzuBot,
    fake_guild: FakeGuild,
    channel: FakeChannel,
    fake_cache: FakeCache,
) -> None:
    before = _member(fake_guild, 424242, pending=True)
    after = _member(fake_guild, 424242, pending=False)
    await _fire(seeded_bot, before, after, fake_cache)
    assert channel.sent == []


async def test_last_welcomed_guard_prevents_double(
    seeded_bot: CazzuBot,
    fake_guild: FakeGuild,
    channel: FakeChannel,
    fake_cache: FakeCache,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _configure(seeded_bot)
    before = _member(fake_guild, 424242, pending=True)
    after = _member(fake_guild, 424242, pending=False)

    monkeypatch.setattr(welcome_cog, "last_welcomed_id", None)  # fresh state
    await _fire(seeded_bot, before, after, fake_cache)
    await _fire(seeded_bot, before, after, fake_cache)  # same id again

    assert len(channel.sent) == 1


async def test_role_mode_welcomes_on_monitored_role(
    seeded_bot: CazzuBot,
    fake_guild: FakeGuild,
    channel: FakeChannel,
    fake_cache: FakeCache,
) -> None:
    monitor = FakeRole(id=500, name="Verified")
    fake_cache.add_role(monitor)
    await _configure(seeded_bot, mode="role", monitor_rid=monitor.id)
    before = _member(fake_guild, 424242)
    after = _member(fake_guild, 424242, roles=[monitor])

    await _fire(seeded_bot, before, after, fake_cache)

    assert channel.sent[-1]["content"] == "hi <@424242>"


async def test_role_mode_ignores_other_roles(
    seeded_bot: CazzuBot,
    fake_guild: FakeGuild,
    channel: FakeChannel,
    fake_cache: FakeCache,
) -> None:
    other = FakeRole(id=501, name="Other")
    fake_cache.add_role(other)
    await _configure(seeded_bot, mode="role", monitor_rid=500)
    before = _member(fake_guild, 424242)
    after = _member(fake_guild, 424242, roles=[other])

    await _fire(seeded_bot, before, after, fake_cache)

    assert channel.sent == []


# -- config commands -------------------------------------------------------


async def test_config_commands_roundtrip(
    bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    role = FakeRole(id=300, name="Member")
    await invoke_command(SetEnabled(), ctx, enabled=True)
    assert await bot.settings.get("welcome.enabled") is True
    await invoke_command(SetChannel(), ctx, channel=channel)
    assert await bot.settings.get("welcome.cid") == 99
    await invoke_command(SetRole(), ctx, role=role)
    assert await bot.settings.get("welcome.default_rid") == 300
    await invoke_command(SetMode(), ctx, mode="role")
    assert await bot.settings.get("welcome.mode") == "role"
    assert ctx.sent[-1].content == "✓ Welcome mode set to role"


async def test_welcome_set_mode_rejects_invalid(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(UserInputError):
        await invoke_command(SetMode(), ctx, mode="bogus")


async def test_welcome_set_message_verifies_and_stores(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await invoke_command(
        SetMessage(), ctx, message='{"content": "hi {mention}"}'
    )
    stored = await bot.settings.get("welcome.message")
    assert stored is not None and stored["content"] == "hi {mention}"
    with pytest.raises(UserInputError):
        await invoke_command(SetMessage(), ctx, message='{"content": 42}')


async def test_welcome_demo_and_raw(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await invoke_command(Demo(), ctx)
    assert ctx.sent[-1].content == "No welcome message has been set."
    await invoke_command(Raw(), ctx)
    assert ctx.sent[-1].content is not None
    assert "null" in ctx.sent[-1].content  # json.dumps(None)
