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
from plugins.experience import db as exp_db
from plugins.experience.extension import Card, QuietAdd, TopMenu
from tests.fakes import (
    invoke_command,
    FakeChannel,
    FakeContext,
    FakeInteraction,
    FakeMember,
    FakeMenuContext,
    FakeUser,
    menu_button,
)

_AUTHOR_ID = 424242


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

    async def _resolve(_bot: object, uid: int) -> object:
        return users.get(uid)

    monkeypatch.setattr("cazzubot.utils.find_user", _resolve)


async def test_exp_no_experience_embed(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await invoke_command(Card(), ctx, user=author)
    embed = ctx.sent[0].embed
    assert embed is not None and embed.author is not None
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

    await invoke_command(Card(), ctx, user=author)

    embed = ctx.sent[0].embed
    assert embed is not None and embed.author is not None
    assert embed.author.name == "cirno's Club Membership Card"
    assert embed.description is not None
    assert "reimu" in embed.description  # resolved via find_user stub
    assert "Rank:" in embed.description
    assert "Level:" in embed.description


def _make_menu(bot: CazzuBot, ctx: FakeContext) -> TopMenu:
    rows = [(1, ctx.member.id, 100)]
    return TopMenu(
        bot, cast(Any, ctx), pendulum.datetime(2026, 1, 1), rows, page=1
    )


async def test_topview_denies_foreign_user(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    menu = _make_menu(bot, ctx)
    foreign = FakeMember(id=999, name="other")
    mctx = FakeMenuContext(FakeInteraction(id=1, member=foreign))
    button = menu_button(menu, 2)
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
    button = menu_button(menu, 2)
    await button.callback(mctx)
    embed = mctx.sent[0].embed
    # one row -> max page is 1 -> next_page stays on page 1
    assert embed is not None
    assert "Page: **`1`**" in embed.description


async def test_quiet_add_then_warn(
    bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    await invoke_command(QuietAdd(), ctx, channel=channel)
    assert ctx.sent[-1].content == "✓ Added <#99> to the quiet list"
    assert await bot.settings.get("level.quiet") == [99]

    await invoke_command(QuietAdd(), ctx, channel=channel)
    assert ctx.sent[-1].content == "⚠︎ Channel already in the quiet list"
