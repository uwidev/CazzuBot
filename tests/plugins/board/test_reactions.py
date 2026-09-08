# pyright: reportArgumentType=false
"""Board plugin — reaction exclusion tests: emoji match, auth matrix
(owner / role / nobody), bot's-own ignored, idempotent add/remove.

Drives the real ``guild_listener``-wrapped handlers with lightweight fake
reaction events (``app`` = the booted bot, ``guild_id`` = its guild), so
the guild gate and the whole toggle path are exercised.
"""

from __future__ import annotations

from types import SimpleNamespace

import pendulum

from core.bot import CazzuBot
from plugins.board import db as board_db
from plugins.board.reactions import (
    DEFAULT_EXCLUDE_EMOJI,
    EXCLUDE_EMOJI_KEY,
    EXCLUDE_ROLE_KEY,
    on_reaction_add,
    on_reaction_remove,
)
from tests.fakes import FakeGuild, FakeMember, FakeRole

_TS = "2026-08-03T00:00:00+00:00"


class _FakeReactionEvent:
    """Minimal GuildReaction{Add,Delete}Event stand-in for the listeners."""

    def __init__(
        self,
        bot: CazzuBot,
        *,
        user_id: int,
        message_id: int = 10,
        emoji_name: str = DEFAULT_EXCLUDE_EMOJI,
        emoji_id: int | None = None,
        member: FakeMember | None = None,
    ) -> None:
        self.app = bot
        self.guild_id = bot.config.guild_id
        self.channel_id = 99
        self.message_id = message_id
        self.user_id = user_id
        self.emoji_name = emoji_name
        self.emoji_id = emoji_id
        self.member = member


async def _seed_row(bot: CazzuBot, message_id: int) -> None:
    await board_db.add_image(
        bot.db,
        _TS,
        f"https://example.com/{message_id}.png",
        f"https://discord.com/channels/2/99/{message_id}",
        f"hash-{message_id}",
        99,
        message_id,
    )


async def _excluded_ids(bot: CazzuBot) -> list[int]:
    rows = await bot.db.fetchall(
        "SELECT message_id FROM board_exclusions ORDER BY message_id"
    )
    return [r["message_id"] for r in rows]


async def test_add_excludes_and_remove_reincludes(bot: CazzuBot) -> None:
    await _seed_row(bot, 1)
    owner = _FakeReactionEvent(bot, user_id=1, message_id=1)

    await on_reaction_add(owner)
    assert await _excluded_ids(bot) == [1]

    await on_reaction_remove(owner)
    assert await _excluded_ids(bot) == []


async def test_toggle_is_idempotent(bot: CazzuBot) -> None:
    await _seed_row(bot, 1)
    owner = _FakeReactionEvent(bot, user_id=1, message_id=1)

    await on_reaction_add(owner)
    await on_reaction_add(owner)  # re-react adds nothing
    assert await _excluded_ids(bot) == [1]

    await on_reaction_remove(owner)
    await on_reaction_remove(owner)  # removing twice is a no-op
    assert await _excluded_ids(bot) == []


async def test_non_matching_emoji_ignored(bot: CazzuBot) -> None:
    await _seed_row(bot, 1)
    event = _FakeReactionEvent(
        bot, user_id=1, message_id=1, emoji_name="👍"
    )
    await on_reaction_add(event)
    assert await _excluded_ids(bot) == []
    await on_reaction_remove(event)
    assert await _excluded_ids(bot) == []


async def test_custom_emoji_setting_matches_by_id_or_name(
    bot: CazzuBot,
) -> None:
    await _seed_row(bot, 1)
    await bot.settings.set(EXCLUDE_EMOJI_KEY, "12345")
    owner = _FakeReactionEvent(
        bot,
        user_id=1,
        message_id=1,
        emoji_name="board_off",
        emoji_id=12345,
    )
    await on_reaction_add(owner)
    assert await _excluded_ids(bot) == [1]

    # a cleared emoji setting disables the toggle entirely
    await bot.settings.set(EXCLUDE_EMOJI_KEY, "")
    await on_reaction_remove(owner)
    assert await _excluded_ids(bot) == [1]


async def test_auth_matrix_add(bot: CazzuBot) -> None:
    guild = FakeGuild(id=2, owner_id=1)
    await _seed_row(bot, 1)
    await _seed_row(bot, 2)
    await _seed_row(bot, 3)
    await _seed_row(bot, 4)
    member = FakeMember(id=424242, name="cirno", guild=guild)

    # no role configured → owner only; owner works, nobody else does
    await on_reaction_add(_FakeReactionEvent(bot, user_id=1, message_id=1))
    await on_reaction_add(
        _FakeReactionEvent(
            bot, user_id=424242, message_id=2, member=member
        )
    )
    assert await _excluded_ids(bot) == [1]

    # role configured → holder works, a member without it does not
    await bot.settings.set(EXCLUDE_ROLE_KEY, 55)
    holder = FakeMember(
        id=777,
        name="mod",
        guild=guild,
        roles=[FakeRole(id=55, name="mod")],
    )
    await on_reaction_add(
        _FakeReactionEvent(bot, user_id=777, message_id=3, member=holder)
    )
    await on_reaction_add(
        _FakeReactionEvent(
            bot, user_id=424242, message_id=4, member=member
        )
    )
    assert await _excluded_ids(bot) == [1, 3]


async def test_remove_is_also_authorization_gated(bot: CazzuBot) -> None:
    guild = FakeGuild(id=2, owner_id=1)
    await _seed_row(bot, 1)
    await board_db.add_exclusion(
        bot.db, 1, 1, pendulum.now("UTC").isoformat()
    )
    await bot.settings.set(EXCLUDE_ROLE_KEY, 55)
    nobody = FakeMember(id=424242, name="cirno", guild=guild)
    await on_reaction_remove(
        _FakeReactionEvent(
            bot, user_id=424242, message_id=1, member=nobody
        )
    )
    assert await _excluded_ids(bot) == [1]  # still excluded


async def test_bots_own_reactions_ignored(
    bot: CazzuBot, monkeypatch
) -> None:
    await _seed_row(bot, 1)
    monkeypatch.setattr(bot, "get_me", lambda: SimpleNamespace(id=666))
    bot_event = _FakeReactionEvent(bot, user_id=666, message_id=1)
    await on_reaction_add(bot_event)
    assert await _excluded_ids(bot) == []
    await on_reaction_remove(bot_event)
    assert await _excluded_ids(bot) == []
