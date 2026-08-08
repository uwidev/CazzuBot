"""Experience extension tests — membership card, pager menu, quiet list.

Invokes the lightbulb command classes directly with a fake context and
seeded option values; asserts on recorded sends + resulting DB state.
Permission hooks are bypassed by direct invocation — those get dedicated
dispatch-level tests.
"""

from __future__ import annotations

from typing import Any, cast

import pendulum
import pytest

from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from plugins.experience import db as exp_db
from plugins.experience.cog import Card, QuietAdd, Top, TopMenu
from tests.fakes import (
    FakeChannel,
    FakeContext,
    FakeInteraction,
    FakeMember,
    FakeMenuContext,
    FakeUser,
)

_AUTHOR_ID = 424242


async def _invoke(
    command: object, ctx: FakeContext, **options: Any
) -> None:
    """Seed a command's option values and run its invoke."""
    cmd = cast(Any, command)
    # lightbulb fills _localized_name during client registration; without
    # a client, seed it from the declared names so descriptors resolve.
    for name in cmd._command_data.options:  # pyright: ignore[reportPrivateUsage]
        descriptor = type(cmd).__dict__[name]
        descriptor._data._localized_name = name  # pyright: ignore[reportPrivateUsage]
        cmd._resolved_option_cache[name] = options.get(name)  # pyright: ignore[reportPrivateUsage]
    cmd._current_context = ctx  # pyright: ignore[reportPrivateUsage]
    await cmd.invoke(ctx)


async def _seed_exp(bot: CazzuBot, uid: int, amount: int) -> None:
    """Give ``uid`` ``amount`` lifetime/seasonal exp (via the exp logs)."""
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, uid)
    await exp_db.add_exp_log(bot.db, uid, amount, now)
    await exp_db.sync_with_exp_logs(bot.db)


def _stub_user_lookup(
    monkeypatch: pytest.MonkeyPatch,
    users: dict[int, FakeMember | FakeUser],
) -> None:
    """Make utils.find_user resolve from a dict (no cache/fetch)."""

    async def _resolve(_bot: object, _ctx: object, uid: int) -> object:
        return users.get(uid)

    monkeypatch.setattr("cazzubot.utils.find_user", _resolve)


async def test_exp_no_experience_embed(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await _invoke(Card(), ctx, user=author)
    embed = ctx.sent[0].embed
    assert embed is not None
    assert embed.author.name == "cirno's Club Membership Card"
    assert embed.description is not None
    assert "has no experience yet." in embed.description


async def test_exp_membership_card(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = FakeUser(id=777, name="reimu")
    _stub_user_lookup(monkeypatch, {author.id: author, other.id: other})
    await _seed_exp(bot, author.id, 100)
    await _seed_exp(bot, other.id, 50)

    await _invoke(Card(), ctx, user=author)

    embed = ctx.sent[0].embed
    assert embed is not None
    assert embed.author.name == "cirno's Club Membership Card"
    assert embed.description is not None
    assert "reimu" in embed.description  # resolved via find_user stub
    assert "Rank:" in embed.description
    assert "Level:" in embed.description


async def test_exp_top_rejects_invalid_season(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(UserInputError):
        await _invoke(Top(), ctx, season=99)


def _make_menu(bot: CazzuBot, ctx: FakeContext) -> TopMenu:
    rows = [(1, ctx.member.id, 100)]
    return TopMenu(bot, ctx, pendulum.datetime(2026, 1, 1), rows, page=1)


def _buttons(menu: TopMenu) -> list[Any]:
    return cast(list[Any], menu._rows[0])  # pyright: ignore[reportPrivateUsage]


async def test_topview_denies_foreign_user(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    menu = _make_menu(bot, ctx)
    foreign = FakeMember(id=999, name="other")
    mctx = FakeMenuContext(FakeInteraction(id=1, member=foreign))
    button = _buttons(menu)[2]
    await button.callback(mctx)
    assert mctx.sent[0].content == "This leaderboard is not yours to page."
    assert mctx.sent[0].ephemeral is True


async def test_topview_pages_for_author(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_user_lookup(monkeypatch, {author.id: author})
    menu = _make_menu(bot, ctx)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=author))
    button = _buttons(menu)[2]
    await button.callback(mctx)
    embed = mctx.edits[0]["embed"]
    # one row -> max page is 1 -> next_page stays on page 1
    assert embed.description is not None
    assert "Page: **`1`**" in embed.description


async def test_quiet_add_then_warn(
    bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    await _invoke(QuietAdd(), ctx, channel=channel)
    assert ctx.sent[-1].content == "✓ Added <#99> to the quiet list"
    assert await bot.settings.get("level.quiet") == [99]

    await _invoke(QuietAdd(), ctx, channel=channel)
    assert ctx.sent[-1].content == "⚠︎ Channel already in the quiet list"
