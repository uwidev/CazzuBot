"""Ranks/levels presentation — handle_ranks + handle_level_up.

These are the cross-plugin services the experience controller calls. They
still take ``bot``/``message`` (discord objects) — the remaining CSR step —
but are fully testable offline with the fakes.
"""

from __future__ import annotations

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.models import WindowEnum
from plugins.levels.logic import handle_level_up
from plugins.ranks import db as ranks_db
from plugins.ranks.logic import handle_ranks
from tests.fakes import (
    FakeChannel,
    FakeGuild,
    FakeMember,
    FakeMessage,
    FakeRole,
)


def _msg(author: FakeMember, channel: FakeChannel) -> FakeMessage:
    assert author.guild is not None
    return FakeMessage(
        id=1,
        content="hi",
        author=author,
        guild=author.guild,
        channel=channel,
    )


async def _enable_ranks(bot: CazzuBot, mode: WindowEnum) -> None:
    await ranks_db.set_enabled(bot.settings, True, mode)


# -- handle_level_up --------------------------------------------------------


async def test_level_up_noop_without_level_gain(
    bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await handle_level_up(bot, _msg(author, channel), utils.OldNew(5, 5))
    assert channel.sent == []


async def test_level_up_quiet_channel_reaction(
    bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await bot.settings.set("level.quiet", [channel.id])
    await bot.settings.set("level.message", {"content": "level up!"})
    message = _msg(author, channel)
    await handle_level_up(bot, message, utils.OldNew(0, 1))
    assert channel.sent == []
    assert message.reactions == ["🎉"]


async def test_level_up_sends_formatted_message(
    bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await bot.settings.set(
        "level.message",
        {"content": "{name} leveled {level_old}->{level_new}"},
    )
    await handle_level_up(
        bot,
        _msg(author, channel),
        utils.OldNew(0, 1),
        delete_after=7,
    )
    assert channel.sent[0]["content"] == "cirno leveled 0->1"
    assert channel.sent[0]["delete_after"] == 7


# -- handle_ranks -----------------------------------------------------------


async def test_rank_up_adds_role_and_notifies(
    bot: CazzuBot,
    channel: FakeChannel,
    author: FakeMember,
    fake_guild: FakeGuild,
) -> None:
    role = FakeRole(id=111, name="Frog King")
    fake_guild.add_role(role)
    await _enable_ranks(bot, WindowEnum.SEASONAL)
    await ranks_db.add(bot.db, 111, 5)
    await ranks_db.set_message(
        bot.settings,
        {"content": "rank up to {rank_new}"},
        WindowEnum.SEASONAL,
    )

    await handle_ranks(
        bot,
        _msg(author, channel),
        utils.OldNew(4, 5),  # crossed threshold 5
        utils.OldNew(0, 0),
    )

    assert role in author.added_roles
    assert channel.sent[0]["content"] == "rank up to <@&111>"


async def test_rank_demotion_removes_roles(
    bot: CazzuBot,
    channel: FakeChannel,
    author: FakeMember,
    fake_guild: FakeGuild,
) -> None:
    role = FakeRole(id=111, name="Frog King")
    fake_guild.add_role(role)
    author = FakeMember(
        id=424242, name="cirno", guild=fake_guild, roles=[role]
    )
    fake_guild.add_member(author)
    await _enable_ranks(bot, WindowEnum.SEASONAL)
    await ranks_db.add(bot.db, 111, 5)

    await handle_ranks(
        bot,
        _msg(author, channel),
        utils.OldNew(5, 4),  # fell below threshold 5
        utils.OldNew(0, 0),
    )

    assert role in author.removed_roles


async def test_ranks_disabled_are_noop(
    bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await ranks_db.add(bot.db, 111, 5)
    await handle_ranks(
        bot,
        _msg(author, channel),
        utils.OldNew(4, 5),
        utils.OldNew(0, 0),
    )
    assert author.added_roles == []
