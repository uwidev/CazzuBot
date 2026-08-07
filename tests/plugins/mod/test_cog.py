"""Mod cog + scheduler due-handler tests (characterization).

Direct invocation bypasses the ``cog_check`` permission gate; the gate itself
gets its own test below. Network edges (fetch_member/fetch_user/unban) stop
at fakes or monkeypatched stubs.
"""

from __future__ import annotations

import pendulum
import pytest
from discord.ext import commands

from cazzubot.bot import CazzuBot
from plugins.mod.cog import ModCog, on_modlog_due
from plugins.mod.db import MUTE_ROLE_KEY
from plugins.mod.logic import split_duration_reason
from tests.fakes import (
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeMember,
    FakeRole,
    FakeUser,
    seed_guild,
)

_MUTE_RID = 500


def _cog(bot: CazzuBot) -> ModCog:
    cog = bot.get_cog(ModCog.__cog_name__)
    assert isinstance(cog, ModCog)
    return cog


def _mute_role(guild: FakeGuild) -> FakeRole:
    role = FakeRole(id=_MUTE_RID, name="Muted")
    guild.add_role(role)
    return role


def _ctx_for(
    bot: CazzuBot, guild: FakeGuild, member: FakeMember
) -> FakeContext:
    return FakeContext(
        bot=bot,
        author=member,
        guild=guild,
        channel=guild.get_channel(99) or FakeChannel(id=99, guild=guild),
    )


# -- pure helpers ---------------------------------------------------------


def test_split_duration_reason() -> None:
    # the first leading prefix that parses is the duration, extended
    # greedily over duration-like tokens; the remainder is the reason
    dur, rest = split_duration_reason("1h rule break")
    assert dur is not None and rest == "rule break"
    dur2, rest2 = split_duration_reason("no duration")
    assert dur2 is None and rest2 == "no duration"
    assert split_duration_reason(None) == (None, "")
    # natural multi-word phrasings (regression: used to silently become
    # a no-expiry mute/ban)
    dur3, rest3 = split_duration_reason("2 hours being bad")
    assert dur3 is not None and rest3 == "being bad"
    dur4, rest4 = split_duration_reason("in 2 hours spam")
    assert dur4 is not None and rest4 == "spam"
    dur5, rest5 = split_duration_reason("for being bad")
    assert dur5 is None and rest5 == "for being bad"
    # compound durations fold in, reason words don't
    dur6, rest6 = split_duration_reason("2 hours 5 minutes being bad")
    assert dur6 is not None and rest6 == "being bad"
    assert 7490 <= (dur6 - pendulum.now("UTC")).in_seconds() <= 7510
    dur7, rest7 = split_duration_reason("2h 5m being bad")
    assert dur7 is not None and rest7 == "being bad"
    assert 7490 <= (dur7 - pendulum.now("UTC")).in_seconds() <= 7510
    dur8, rest8 = split_duration_reason("2 hours minutes")
    assert dur8 is not None and rest8 == "minutes"


# -- warn / mute / unmute -------------------------------------------------


async def test_warn_writes_modlog(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await _cog(bot).warn(ctx, author, reason="spam")
    row = await bot.db.fetchone("SELECT * FROM modlog ORDER BY id DESC")
    assert row is not None
    assert row["log_type"] == "warn" and row["uid"] == author.id
    assert row["reason"] == "spam"
    assert ctx.sent[-1].content == f"Warned {author}"


async def test_mute_without_role_hints(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await _cog(bot).mute(ctx, author, raw="1 hour test")
    assert ctx.sent[-1].content == (
        "No mute role has been set (`set mute <role>`)."
    )


async def test_mute_applies_role_logs_and_schedules(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    fake_guild: FakeGuild,
) -> None:
    role = _mute_role(fake_guild)
    await bot.settings.set(MUTE_ROLE_KEY, role.id)

    await _cog(bot).mute(ctx, author, raw="1h rule break")

    assert role in author.added_roles
    tasks = await bot.scheduler.get("modlog")
    assert len(tasks) == 1
    assert tasks[0].payload == {
        "uid": author.id,
        "log_type": "mute",
    }
    row = await bot.db.fetchone("SELECT * FROM modlog ORDER BY id DESC")
    assert row is not None
    assert row["log_type"] == "mute" and row["reason"] == "rule break"
    assert ctx.sent[-1].content == f"Muted {author}"


async def test_mute_rejects_past_time(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    fake_guild: FakeGuild,
) -> None:
    _mute_role(fake_guild)
    await bot.settings.set(MUTE_ROLE_KEY, _MUTE_RID)
    with pytest.raises(commands.BadArgument):
        await _cog(bot).mute(ctx, author, raw="yesterday bad")


async def test_unmute_removes_role_and_drops_tasks(
    bot: CazzuBot,
    ctx: FakeContext,
    fake_guild: FakeGuild,
) -> None:
    role = _mute_role(fake_guild)
    await bot.settings.set(MUTE_ROLE_KEY, role.id)
    muted = FakeMember(
        id=777, name="muted", guild=fake_guild, roles=[role]
    )
    fake_guild.add_member(muted)
    await bot.scheduler.add(
        "modlog",
        pendulum.now("UTC").add(hours=1),
        {"uid": muted.id, "log_type": "mute"},
    )

    await _cog(bot).unmute(ctx, muted)

    assert role in muted.removed_roles
    assert await bot.scheduler.get("modlog") == []
    assert ctx.sent[-1].content == f"Unmuted {muted}"


# -- ban / unban -----------------------------------------------------------


async def test_ban_schedules_tempban(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await _cog(bot).ban(ctx, author, raw="2h being bad")
    assert author.banned == ["being bad"]
    tasks = await bot.scheduler.get("modlog")
    assert len(tasks) == 1
    assert tasks[0].payload["log_type"] == "tempban"
    row = await bot.db.fetchone("SELECT * FROM modlog ORDER BY id DESC")
    assert row is not None and row["log_type"] == "tempban"


async def test_unban_drops_tempban_task(
    bot: CazzuBot, ctx: FakeContext, fake_guild: FakeGuild
) -> None:
    user = FakeUser(id=999, name="banned")
    await bot.scheduler.add(
        "modlog",
        pendulum.now("UTC").add(hours=1),
        {"uid": user.id, "log_type": "tempban"},
    )

    await _cog(bot).unban(ctx, user)

    assert len(fake_guild.unbanned) == 1
    assert fake_guild.unbanned[0][0] is user
    assert await bot.scheduler.get("modlog") == []


# -- scheduler due handler -------------------------------------------------


async def test_on_modlog_due_lifts_mute(
    bot: CazzuBot, fake_guild: FakeGuild
) -> None:
    role = _mute_role(fake_guild)
    await bot.settings.set(MUTE_ROLE_KEY, role.id)
    muted = FakeMember(
        id=777, name="muted", guild=fake_guild, roles=[role]
    )
    fake_guild.add_member(muted)
    seed_guild(bot, fake_guild)

    await on_modlog_due(bot, {"uid": muted.id, "log_type": "mute"})

    assert role in muted.removed_roles


async def test_on_modlog_due_ends_tempban(
    bot: CazzuBot,
    fake_guild: FakeGuild,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_guild(bot, fake_guild)
    user = FakeUser(id=999, name="banned")

    async def _fetch_user(uid: int) -> FakeUser:
        assert uid == user.id
        return user

    monkeypatch.setattr(bot, "fetch_user", _fetch_user)

    await on_modlog_due(bot, {"uid": user.id, "log_type": "tempban"})

    assert len(fake_guild.unbanned) == 1
    assert fake_guild.unbanned[0][0] is user


# -- permission gate + slowmode + settings --------------------------------


async def test_cog_check_requires_mod_perms(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    cog = _cog(bot)
    assert await cog.cog_check(ctx) is False  # plain member

    admin = FakeMember(
        id=888, name="admin", guild=ctx.guild, administrator=True
    )
    assert ctx.guild is not None
    admin_ctx = _ctx_for(bot, ctx.guild, admin)
    assert await cog.cog_check(admin_ctx) is True


async def test_slowmode_edits_channel(
    bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    await _cog(bot).slowmode(ctx, cooldown=30, channel=channel)
    assert channel.edits == [{"slowmode_delay": 30}]
    assert ctx.sent[-1].content is not None
    assert "30" in ctx.sent[-1].content


async def test_set_mute_role(bot: CazzuBot, ctx: FakeContext) -> None:
    role = FakeRole(id=_MUTE_RID, name="Muted")
    await _cog(bot).set_mute(ctx, role=role)
    assert await bot.settings.get(MUTE_ROLE_KEY) == _MUTE_RID
