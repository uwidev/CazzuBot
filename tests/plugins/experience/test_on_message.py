# pyright: reportArgumentType=false
"""on_message exp pipeline — characterization tests.

These pin CURRENT behavior of the exp award pipeline (award, cooldown, guild/
bot guards, cross-plugin handler wiring). The listener is invoked directly
(``plugins.experience.extension.on_message``) with a fake ``MessageCreateEvent``
rather than via bot.dispatch: dispatch only schedules listener tasks, and
other plugins' message listeners are out of scope here.
"""

from __future__ import annotations

import importlib

import pendulum
import pytest

from cazzubot.bot import CazzuBot
from plugins.experience import extension as exp_ext
from plugins.experience import db as exp_db
from tests.fakes import (
    FakeChannel,
    FakeMember,
    FakeMessage,
    FakeMessageCreateEvent,
)

_AUTHOR_ID = 424242
_GUILD_ID = 2
_CHANNEL_ID = 99
# exp awarded for the 1st/2nd message of the day, from the hard-coded rate
# curve (logic module): _from_msg(1) == _from_msg(2) == 20.
_MSG_1_EXP = 20


async def _send(
    bot: CazzuBot, author: FakeMember, channel: FakeChannel, content: str
) -> None:
    msg = FakeMessage(
        id=1,
        content=content,
        author=author,
        guild_id=_GUILD_ID,
        channel_id=channel.id,
    )
    await exp_ext.on_message(FakeMessageCreateEvent(message=msg, app=bot))


async def test_first_message_awards_exp(
    seeded_bot: CazzuBot, author: FakeMember, channel: FakeChannel
) -> None:
    await _send(seeded_bot, author, channel, "hello")
    row = await exp_db.get_member_exp(seeded_bot.db, _AUTHOR_ID)
    assert row is not None
    assert row.msg_cnt == 1
    assert row.lifetime == _MSG_1_EXP
    assert row.cdr is not None  # cooldown armed
    now = pendulum.now("UTC")
    assert (
        await exp_db.seasonal_exp(
            seeded_bot.db, _AUTHOR_ID, now.year, (now.month - 1) // 3
        )
        == _MSG_1_EXP
    )


async def test_bot_author_is_ignored(
    seeded_bot: CazzuBot, channel: FakeChannel
) -> None:
    bot_author = FakeMember(id=111, name="cazzu", bot=True)
    await _send(seeded_bot, bot_author, channel, "beep boop")
    assert await exp_db.get_member_exp(seeded_bot.db, 111) is None


async def test_exp_multiplier_scales_award(
    seeded_bot: CazzuBot, author: FakeMember, channel: FakeChannel
) -> None:
    """A member contribution to the message-exp seam scales the award."""
    from datetime import timedelta

    from cazzubot import statuses
    from cazzubot.statuses import Scope
    from plugins.experience.logic import StatusSeam

    await statuses.publish(
        seeded_bot.db,
        Scope.member(_AUTHOR_ID),
        StatusSeam.MESSAGE_EXP_MULTIPLIER,
        "test",
        {"value": 2.0},
        duration=timedelta(hours=1),
    )
    await _send(seeded_bot, author, channel, "hello")
    row = await exp_db.get_member_exp(seeded_bot.db, _AUTHOR_ID)
    assert row is not None
    assert row.lifetime == _MSG_1_EXP * 2


async def test_wrong_guild_is_ignored(
    seeded_bot: CazzuBot, channel: FakeChannel
) -> None:
    outsider = FakeMember(id=555, name="outsider")
    msg = FakeMessage(
        id=1,
        content="hi",
        author=outsider,
        guild_id=99,  # not the configured guild
        channel_id=channel.id,
    )
    await exp_ext.on_message(
        FakeMessageCreateEvent(message=msg, app=seeded_bot)
    )
    assert await exp_db.get_member_exp(seeded_bot.db, 555) is None


async def test_cooldown_skips_second_message(
    seeded_bot: CazzuBot, author: FakeMember, channel: FakeChannel
) -> None:
    await _send(seeded_bot, author, channel, "first")
    await _send(seeded_bot, author, channel, "second")  # inside cooldown
    row = await exp_db.get_member_exp(seeded_bot.db, _AUTHOR_ID)
    assert row is not None
    assert row.msg_cnt == 1
    assert row.lifetime == _MSG_1_EXP


async def test_cooldown_expiry_allows_next_award(
    seeded_bot: CazzuBot, author: FakeMember, channel: FakeChannel
) -> None:
    await _send(seeded_bot, author, channel, "first")
    row = await exp_db.get_member_exp(seeded_bot.db, _AUTHOR_ID)
    assert row is not None
    await exp_db.update_member_exp(
        seeded_bot.db,
        _AUTHOR_ID,
        lifetime=row.lifetime,
        msg_cnt=row.msg_cnt,
        cdr=pendulum.now("UTC").subtract(seconds=1),
    )
    await _send(seeded_bot, author, channel, "after cooldown")
    row = await exp_db.get_member_exp(seeded_bot.db, _AUTHOR_ID)
    assert row is not None
    assert row.msg_cnt == 2
    assert row.lifetime == _MSG_1_EXP * 2


async def test_level_up_and_rank_handlers_invoked_once_each(
    seeded_bot: CazzuBot,
    author: FakeMember,
    channel: FakeChannel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the cross-plugin wiring: every awarded message reaches both
    handlers exactly once, with that message."""
    calls: list[tuple[str, int]] = []

    async def spy_level_up(
        _bot: object, message: FakeMessage, _level: object, **_kw: object
    ) -> None:
        calls.append(("level", message.id))

    async def spy_ranks(
        _bot: object,
        member: FakeMember,
        _channel_id: object,
        _seasonal: object,
        _lifetime: object,
        **_kw: object,
    ) -> None:
        calls.append(("ranks", member.id))

    monkeypatch.setattr(
        importlib.import_module("plugins.levels.presenter"),
        "present_level_up",
        spy_level_up,
    )
    monkeypatch.setattr(
        importlib.import_module("plugins.ranks.presenter"),
        "present_ranks",
        spy_ranks,
    )

    await _send(seeded_bot, author, channel, "hello")
    assert calls == [("level", 1), ("ranks", _AUTHOR_ID)]
