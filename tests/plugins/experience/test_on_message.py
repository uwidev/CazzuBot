"""on_message exp pipeline — characterization tests.

These pin CURRENT behavior of the exp award pipeline (award, cooldown, guild/
bot guards, cross-plugin handler wiring) so the service extraction in
``plugins/experience/logic.py`` can proceed with a safety net. The listener
is invoked directly (``cog.on_message``) rather than via ``bot.dispatch``:
dispatch only schedules listener tasks, and other plugins' message listeners
are out of scope here.
"""

from __future__ import annotations

import importlib

import pendulum
import pytest

from cazzubot.bot import CazzuBot
from plugins.experience import db as exp_db
from plugins.experience.cog import ExperienceCog
from tests.fakes import (
    FakeChannel,
    FakeGuild,
    FakeMember,
    FakeMessage,
)

_AUTHOR_ID = 424242
# exp awarded for the 1st/2nd message of the day, from the hard-coded rate
# curve (cog module): _from_msg(1) == _from_msg(2) == 20.
_MSG_1_EXP = 20


def _cog(bot: CazzuBot) -> ExperienceCog:
    cog = bot.get_cog(ExperienceCog.__cog_name__)
    assert isinstance(cog, ExperienceCog)
    return cog


async def _send(
    bot: CazzuBot, author: FakeMember, channel: FakeChannel, content: str
) -> None:
    guild = author.guild
    assert guild is not None
    msg = FakeMessage(
        id=1, content=content, author=author, guild=guild, channel=channel
    )
    await _cog(bot).on_message(msg)


async def test_first_message_awards_exp(
    bot: CazzuBot, author: FakeMember, channel: FakeChannel
) -> None:
    await _send(bot, author, channel, "hello")
    row = await exp_db.get_member_exp(bot.db, _AUTHOR_ID)
    assert row is not None
    assert row.msg_cnt == 1
    assert row.lifetime == _MSG_1_EXP
    assert row.cdr is not None  # cooldown armed
    now = pendulum.now("UTC")
    assert (
        await exp_db.seasonal_exp(
            bot.db, _AUTHOR_ID, now.year, (now.month - 1) // 3
        )
        == _MSG_1_EXP
    )


async def test_bot_author_is_ignored(
    bot: CazzuBot, channel: FakeChannel
) -> None:
    bot_author = FakeMember(
        id=111, name="cazzu", bot=True, guild=channel.guild
    )
    await _send(bot, bot_author, channel, "beep boop")
    assert await exp_db.get_member_exp(bot.db, 111) is None


async def test_wrong_guild_is_ignored(
    bot: CazzuBot, channel: FakeChannel
) -> None:
    other_guild = FakeGuild(id=99)
    outsider = FakeMember(id=555, name="outsider", guild=other_guild)
    msg = FakeMessage(
        id=1,
        content="hi",
        author=outsider,
        guild=other_guild,
        channel=channel,
    )
    await _cog(bot).on_message(msg)
    assert await exp_db.get_member_exp(bot.db, 555) is None


async def test_cooldown_skips_second_message(
    bot: CazzuBot, author: FakeMember, channel: FakeChannel
) -> None:
    await _send(bot, author, channel, "first")
    await _send(bot, author, channel, "second")  # inside the 15s cooldown
    row = await exp_db.get_member_exp(bot.db, _AUTHOR_ID)
    assert row is not None
    assert row.msg_cnt == 1
    assert row.lifetime == _MSG_1_EXP


async def test_cooldown_expiry_allows_next_award(
    bot: CazzuBot, author: FakeMember, channel: FakeChannel
) -> None:
    await _send(bot, author, channel, "first")
    row = await exp_db.get_member_exp(bot.db, _AUTHOR_ID)
    assert row is not None
    await exp_db.update_member_exp(
        bot.db,
        _AUTHOR_ID,
        lifetime=row.lifetime,
        msg_cnt=row.msg_cnt,
        cdr=pendulum.now("UTC").subtract(seconds=1),
    )
    await _send(bot, author, channel, "after cooldown")
    row = await exp_db.get_member_exp(bot.db, _AUTHOR_ID)
    assert row is not None
    assert row.msg_cnt == 2
    assert row.lifetime == _MSG_1_EXP * 2


async def test_level_up_and_rank_handlers_invoked_once_each(
    bot: CazzuBot,
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
        message: FakeMessage,
        _seasonal: object,
        _lifetime: object,
        **_kw: object,
    ) -> None:
        calls.append(("ranks", message.id))

    monkeypatch.setattr(
        importlib.import_module("plugins.levels.logic"),
        "handle_level_up",
        spy_level_up,
    )
    monkeypatch.setattr(
        importlib.import_module("plugins.ranks.logic"),
        "handle_ranks",
        spy_ranks,
    )

    await _send(bot, author, channel, "hello")
    assert calls == [("level", 1), ("ranks", 1)]
