# pyright: reportArgumentType=false
"""Ranks/levels presentation — present_ranks + present_level_up.

The presenters are the controller-edge halves of the levels/ranks pipeline
(cross-plugin services the experience controller calls); their *decisions*
(``decide_level_up``, ``plan_rank_changes``) are pure and tested directly
below, the hikari side effects through the rest/cache fakes.
"""

from __future__ import annotations

import pytest
from typing import Any, cast

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.models import WindowEnum
from plugins.levels.logic import LevelUpAction, decide_level_up
from plugins.levels.presenter import present_level_up
from plugins.ranks import db as ranks_db
from plugins.ranks.db import RankThreshold
from plugins.ranks.logic import plan_rank_changes
from plugins.ranks.presenter import present_ranks
from tests.fakes import (
    rest_of,
    FakeCache,
    FakeChannel,
    FakeMember,
    FakeMessage,
    FakeRest,
    FakeRole,
)

_GUILD_ID = 2
_CHANNEL_ID = 99
_RANK_REASON = "Rank up/Rank-role integrity"


def _msg(author: FakeMember, channel: FakeChannel) -> FakeMessage:
    return FakeMessage(
        id=1,
        content="hi",
        author=author,
        guild_id=_GUILD_ID,
        channel_id=channel.id,
    )


async def _enable_ranks(bot: CazzuBot, mode: WindowEnum) -> None:
    await ranks_db.set_enabled(bot.settings, True, mode)


def _thresholds(*pairs: tuple[int, int]) -> list[RankThreshold]:
    return [
        RankThreshold(rid=rid, threshold=lvl, mode=WindowEnum.SEASONAL)
        for rid, lvl in pairs
    ]


# -- decide_level_up (pure) -------------------------------------------------


def test_decide_level_up() -> None:
    assert (
        decide_level_up(
            utils.OldNew(5, 5), ranked_up=False, channel_id=1, quiet_ids=[]
        )
        is LevelUpAction.SKIP  # no level gain
    )
    assert (
        decide_level_up(
            utils.OldNew(0, 1), ranked_up=True, channel_id=1, quiet_ids=[]
        )
        is LevelUpAction.SKIP  # rank up trumps level up
    )
    assert (
        decide_level_up(
            utils.OldNew(0, 1),
            ranked_up=False,
            channel_id=1,
            quiet_ids=[1],
        )
        is LevelUpAction.REACTION  # quiet channel
    )
    assert (
        decide_level_up(
            utils.OldNew(0, 1), ranked_up=False, channel_id=1, quiet_ids=[]
        )
        is LevelUpAction.MESSAGE
    )


# -- plan_rank_changes (pure) -----------------------------------------------


def test_plan_rank_up_keep_old() -> None:
    thresholds = _thresholds((111, 5), (222, 10))
    plan = plan_rank_changes(
        utils.OldNew(4, 12),
        thresholds,
        keep_old=True,
        notify=True,
        member_role_ids=[],
    )
    assert plan.add_ids == [111, 222]
    assert plan.remove_ids == []
    assert plan.notify is True
    assert plan.rid_new == 222


def test_plan_rank_up_no_keep_old() -> None:
    thresholds = _thresholds((111, 5), (222, 10))
    plan = plan_rank_changes(
        utils.OldNew(4, 12),
        thresholds,
        keep_old=False,
        notify=True,
        member_role_ids=[111],  # member holds the old rank
    )
    assert plan.add_ids == [222]
    assert plan.remove_ids == [111]


def test_plan_skip_roles_already_held() -> None:
    thresholds = _thresholds((111, 5), (222, 10))
    plan = plan_rank_changes(
        utils.OldNew(4, 12),
        thresholds,
        keep_old=True,
        notify=True,
        member_role_ids=[111],
    )
    assert plan.add_ids == [222]  # 111 already held


def test_plan_demotion_removes_all() -> None:
    thresholds = _thresholds((111, 5), (222, 10))
    plan = plan_rank_changes(
        utils.OldNew(12, 4),
        thresholds,
        keep_old=True,
        notify=True,
        member_role_ids=[111, 222],
    )
    assert plan.add_ids == []
    assert plan.remove_ids == [111, 222]
    assert plan.notify is False  # fell off the ladder


def test_plan_no_crossing_does_not_notify() -> None:
    thresholds = _thresholds((111, 5))
    plan = plan_rank_changes(
        utils.OldNew(4, 4),
        thresholds,
        keep_old=False,
        notify=True,
        member_role_ids=[],
    )
    assert plan.add_ids == []
    assert plan.notify is False


def test_plan_same_band_crossing_does_not_notify() -> None:
    """Crossing within one threshold band is a level-up, not a rank-up."""
    thresholds = _thresholds((111, 5), (222, 10))
    plan = plan_rank_changes(
        utils.OldNew(6, 8),
        thresholds,
        keep_old=False,
        notify=True,
        member_role_ids=[],
    )
    assert plan.rid_old == 111
    assert plan.rid_new == 111
    assert plan.notify is False


# -- present_level_up -------------------------------------------------------


async def test_level_up_noop_without_level_gain(
    seeded_bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await present_level_up(
        seeded_bot, cast(Any, _msg(author, channel)), utils.OldNew(5, 5)
    )
    assert channel.sent == []


async def test_level_up_quiet_channel_reaction(
    seeded_bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await seeded_bot.settings.set("level.quiet", [channel.id])
    await seeded_bot.settings.set(
        "level.message", {"content": "level up!"}
    )
    message = _msg(author, channel)
    await present_level_up(seeded_bot, message, utils.OldNew(0, 1))
    assert channel.sent == []
    assert rest_of(seeded_bot).reactions == [
        (channel.id, message.id, "🎉")
    ]


async def test_level_up_sends_formatted_message(
    seeded_bot: CazzuBot,
    channel: FakeChannel,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seeded_bot.settings.set(
        "level.message",
        {"content": "{name} leveled {level_old}->{level_new}"},
    )
    scheduled: list[tuple[int, int, float]] = []
    monkeypatch.setattr(
        # templates binds schedule_delete at import, so patch it there
        "cazzubot.templates.schedule_delete",
        lambda _bot, cid, mid, delay: scheduled.append((cid, mid, delay)),
    )
    await present_level_up(
        seeded_bot,
        cast(Any, _msg(author, channel)),
        utils.OldNew(0, 1),
        delete_after=7,
    )
    assert channel.sent[0]["content"] == "cirno leveled 0->1"
    assert scheduled == [(channel.id, 1, 7)]


# -- present_ranks ----------------------------------------------------------


async def test_rank_up_adds_role_and_notifies(
    seeded_bot: CazzuBot,
    channel: FakeChannel,
    author: FakeMember,
    fake_cache: FakeCache,
) -> None:
    role = FakeRole(id=111, name="Frog King")
    fake_cache.add_role(role)
    await _enable_ranks(seeded_bot, WindowEnum.SEASONAL)
    await ranks_db.add(seeded_bot.db, 111, 5)
    await ranks_db.set_message(
        seeded_bot.settings,
        {"content": "rank up to {rank_new}"},
        WindowEnum.SEASONAL,
    )

    await present_ranks(
        seeded_bot,
        author,
        _CHANNEL_ID,
        utils.OldNew(4, 5),  # crossed threshold 5
        utils.OldNew(0, 0),
    )

    assert rest_of(seeded_bot).added_roles == [
        (author.id, role.id, _RANK_REASON)
    ]
    assert channel.sent[0]["content"] == "rank up to <@&111>"


async def test_rank_demotion_removes_roles(
    seeded_bot: CazzuBot,
    channel: FakeChannel,
    fake_cache: FakeCache,
    fake_rest: FakeRest,
) -> None:
    role = FakeRole(id=111, name="Frog King")
    fake_cache.add_role(role)
    author = FakeMember(id=424242, name="cirno", roles=[role])
    fake_cache.add_member(author)
    fake_rest.members[(_GUILD_ID, author.id)] = author
    await _enable_ranks(seeded_bot, WindowEnum.SEASONAL)
    await ranks_db.add(seeded_bot.db, 111, 5)

    await present_ranks(
        seeded_bot,
        author,
        _CHANNEL_ID,
        utils.OldNew(5, 4),  # fell below threshold 5
        utils.OldNew(0, 0),
    )

    assert rest_of(seeded_bot).removed_roles == [
        (author.id, role.id, None)
    ]


async def test_ranks_disabled_are_noop(
    seeded_bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await ranks_db.add(seeded_bot.db, 111, 5)
    await present_ranks(
        seeded_bot,
        author,
        _CHANNEL_ID,
        utils.OldNew(4, 5),
        utils.OldNew(0, 0),
    )
    assert rest_of(seeded_bot).added_roles == []
