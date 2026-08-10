"""Mod extension + scheduler due-handler tests (characterization).

Direct invocation bypasses the ``_mod_gate`` permission hook; the gate itself
gets its own test below. Network edges (fetch_member/fetch_user/unban) stop
at the rest fakes.
"""

from __future__ import annotations

from typing import Any, cast

import pendulum
import pytest

from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from plugins.mod.cog import (
    Ban,
    Kick,
    Mute,
    SetMute,
    Slowmode,
    Unban,
    Unmute,
    Warn,
    on_modlog_due,
)
from plugins.mod.db import MUTE_ROLE_KEY
from plugins.mod.logic import split_duration_reason
from tests.fakes import (
    rest_of,
    FakeCache,
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeMember,
    FakeRest,
    FakeRole,
    FakeUser,
    invoke_command,
)

_MUTE_RID = 500


def _mute_role(fake_cache: FakeCache) -> FakeRole:
    role = FakeRole(id=_MUTE_RID, name="Muted")
    fake_cache.add_role(role)
    return role


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
    seeded_bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await invoke_command(Warn(), ctx, member=author, reason="spam")
    row = await seeded_bot.db.fetchone(
        "SELECT * FROM modlog ORDER BY id DESC"
    )
    assert row is not None
    assert row["log_type"] == "warn" and row["uid"] == author.id
    assert row["reason"] == "spam"
    assert ctx.sent[-1].content == f"Warned {author}"


async def test_mute_without_role_hints(
    seeded_bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await invoke_command(Mute(), ctx, member=author, raw="1 hour test")
    assert ctx.sent[-1].content == (
        "No mute role has been set (`set mute <role>`)."
    )


async def test_mute_applies_role_logs_and_schedules(
    seeded_bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    fake_cache: FakeCache,
) -> None:
    role = _mute_role(fake_cache)
    await seeded_bot.settings.set(MUTE_ROLE_KEY, role.id)

    await invoke_command(Mute(), ctx, member=author, raw="1h rule break")

    assert rest_of(seeded_bot).added_roles == [
        (author.id, role.id, "rule break")
    ]
    tasks = await seeded_bot.scheduler.get("modlog")
    assert len(tasks) == 1
    assert tasks[0].payload == {
        "uid": author.id,
        "log_type": "mute",
        "retry": True,
    }
    row = await seeded_bot.db.fetchone(
        "SELECT * FROM modlog ORDER BY id DESC"
    )
    assert row is not None
    assert row["log_type"] == "mute" and row["reason"] == "rule break"
    assert ctx.sent[-1].content == f"Muted {author}"


async def test_mute_rejects_past_time(
    seeded_bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    fake_cache: FakeCache,
) -> None:
    _mute_role(fake_cache)
    await seeded_bot.settings.set(MUTE_ROLE_KEY, _MUTE_RID)
    with pytest.raises(UserInputError):
        await invoke_command(
            Mute(), ctx, member=author, raw="yesterday bad"
        )


async def test_unmute_removes_role_and_drops_tasks(
    seeded_bot: CazzuBot,
    ctx: FakeContext,
    fake_cache: FakeCache,
    fake_rest: FakeRest,
    fake_guild: FakeGuild,
) -> None:
    role = _mute_role(fake_cache)
    await seeded_bot.settings.set(MUTE_ROLE_KEY, role.id)
    muted = FakeMember(
        id=777, name="muted", guild=fake_guild, roles=[role]
    )
    fake_cache.add_member(muted)
    fake_rest.members[(2, muted.id)] = muted
    await seeded_bot.scheduler.add(
        "modlog",
        pendulum.now("UTC").add(hours=1),
        {"uid": muted.id, "log_type": "mute"},
    )

    await invoke_command(Unmute(), ctx, member=muted)

    assert rest_of(seeded_bot).removed_roles == [
        (muted.id, role.id, "Unmuted.")
    ]
    assert await seeded_bot.scheduler.get("modlog") == []
    assert ctx.sent[-1].content == f"Unmuted {muted}"


# -- ban / unban -----------------------------------------------------------


async def test_ban_schedules_tempban(
    seeded_bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await invoke_command(Ban(), ctx, member=author, raw="2h being bad")
    assert rest_of(seeded_bot).banned == [(author.id, "being bad")]
    tasks = await seeded_bot.scheduler.get("modlog")
    assert len(tasks) == 1
    assert tasks[0].payload["log_type"] == "tempban"
    row = await seeded_bot.db.fetchone(
        "SELECT * FROM modlog ORDER BY id DESC"
    )
    assert row is not None and row["log_type"] == "tempban"


async def test_kick_writes_modlog(
    seeded_bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await invoke_command(Kick(), ctx, member=author, reason="bye")
    assert rest_of(seeded_bot).kicked == [(author.id, "bye")]
    row = await seeded_bot.db.fetchone(
        "SELECT * FROM modlog ORDER BY id DESC"
    )
    assert row is not None and row["log_type"] == "kick"


async def test_unban_drops_tempban_task(
    seeded_bot: CazzuBot, ctx: FakeContext, fake_guild: object
) -> None:
    user = FakeUser(id=999, name="banned")
    await seeded_bot.scheduler.add(
        "modlog",
        pendulum.now("UTC").add(hours=1),
        {"uid": user.id, "log_type": "tempban"},
    )

    await invoke_command(Unban(), ctx, user=user)

    assert rest_of(seeded_bot).unbanned == [(user.id, "Unbanned.")]
    assert await seeded_bot.scheduler.get("modlog") == []


# -- scheduler due handler -------------------------------------------------


async def test_on_modlog_due_lifts_mute(
    seeded_bot: CazzuBot,
    fake_cache: FakeCache,
    fake_rest: FakeRest,
    fake_guild: FakeGuild,
) -> None:
    role = _mute_role(fake_cache)
    await seeded_bot.settings.set(MUTE_ROLE_KEY, role.id)
    muted = FakeMember(
        id=777, name="muted", guild=fake_guild, roles=[role]
    )
    fake_cache.add_member(muted)
    fake_rest.members[(2, muted.id)] = muted

    await on_modlog_due(seeded_bot, {"uid": muted.id, "log_type": "mute"})

    assert rest_of(seeded_bot).removed_roles == [
        (muted.id, role.id, "Mute expired.")
    ]


async def test_on_modlog_due_ends_tempban(
    seeded_bot: CazzuBot, fake_rest: FakeRest
) -> None:
    user = FakeUser(id=999, name="banned")
    fake_rest.users[user.id] = user

    await on_modlog_due(
        seeded_bot, {"uid": user.id, "log_type": "tempban"}
    )

    assert rest_of(seeded_bot).unbanned == [(user.id, "Tempban expired.")]


# -- permission gate + slowmode + settings --------------------------------


async def test_mod_gate_requires_mod_perms(
    seeded_bot: CazzuBot,
    ctx: FakeContext,
    channel: FakeChannel,
    fake_guild: FakeGuild,
) -> None:
    from plugins.mod.cog import _ModGateDenied, _mod_gate

    with pytest.raises(_ModGateDenied):
        await cast(Any, _mod_gate)(None, ctx)  # plain member

    admin = FakeMember(id=888, name="admin", administrator=True)
    admin_ctx = FakeContext(
        bot=seeded_bot,
        member=admin,
        guild=fake_guild,
        channel=channel,
    )
    await cast(Any, _mod_gate)(None, admin_ctx)  # no raise


async def test_slowmode_edits_channel(
    seeded_bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    await invoke_command(Slowmode(), ctx, cooldown=30, channel=channel)
    assert rest_of(seeded_bot).channel_edits == [
        (channel.id, {"rate_limit_per_user": 30})
    ]
    assert ctx.sent[-1].content is not None
    assert "30" in ctx.sent[-1].content


async def test_set_mute_role(
    seeded_bot: CazzuBot, ctx: FakeContext
) -> None:
    role = FakeRole(id=_MUTE_RID, name="Muted")
    await invoke_command(SetMute(), ctx, role=role)
    assert await seeded_bot.settings.get(MUTE_ROLE_KEY) == _MUTE_RID
