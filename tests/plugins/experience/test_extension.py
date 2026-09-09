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

from core.bot import CazzuBot
from core.errors import UserInputError
from plugins.experience import db as exp_db
from plugins.experience.extension import (
    Leaderboard,
    QuietAdd,
    TopMenu,
    View,
)
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

    monkeypatch.setattr("core.utils.find_user", _resolve)


async def test_exp_no_experience_embed(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await invoke_command(View(), ctx, user=author)
    embed = ctx.sent[0].embed
    assert embed is not None and embed.author is not None
    assert embed.author.name == "cirno's Club Membership Card"
    assert embed.description is not None
    assert "has no experience yet." in embed.description
    # the empty card is window-scoped too — a member with lifetime exp but
    # nothing this season must not read this as their all-time standing
    now = pendulum.now("UTC")
    season = (now.month - 1) // 3 + 1
    assert (
        f"Window: **`Season {season}, {now.year}`**" in embed.description
    )


async def test_exp_lifetime_mode(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_user_lookup(monkeypatch, {author.id: author})
    await _seed_exp(bot, author.id, 100)

    await invoke_command(View(), ctx, user=author, mode="lifetime")

    embed = ctx.sent[0].embed
    assert embed is not None and embed.author is not None
    assert embed.author.name == "cirno's Club Membership Card"
    assert embed.description is not None
    assert "Experience: **`100`**" in embed.description
    # the window line is the only thing telling the two modes apart
    assert "Window: **`All time`**" in embed.description


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

    await invoke_command(View(), ctx, user=author)

    embed = ctx.sent[0].embed
    assert embed is not None and embed.author is not None
    assert embed.author.name == "cirno's Club Membership Card"
    assert embed.description is not None
    assert "reimu" in embed.description  # resolved via find_user stub
    assert "Rank:" in embed.description
    assert "Level:" in embed.description
    # rank 1 of the 2 seeded members
    assert "in the top `50%` of all members!" in embed.description
    # the seasonal card names its window (the default mode)
    now = pendulum.now("UTC")
    season = (now.month - 1) // 3 + 1
    assert (
        f"Window: **`Season {season}, {now.year}`**" in embed.description
    )
    # the board's ANSI row colors only render in an ansi fence
    assert "```ansi" in embed.description


def _make_menu(bot: CazzuBot, ctx: FakeContext) -> TopMenu:
    rows = [(1, ctx.member.id, 100)]
    return TopMenu(
        bot, cast(Any, ctx), pendulum.datetime(2026, 1, 1), rows, page=1
    )


async def _skip_attach(*_args: Any, **_kwargs: Any) -> None:
    """Stand in for ``Menu.attach``: no 30s interaction wait in unit tests."""
    return None


async def test_exp_lifetime_leaderboard(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``mode:lifetime`` boards the all-time window, with no season fields."""
    _stub_user_lookup(monkeypatch, {author.id: author})
    await _seed_exp(bot, author.id, 100)
    monkeypatch.setattr(TopMenu, "attach", _skip_attach)

    await invoke_command(Leaderboard(), ctx, mode="lifetime")

    embed = ctx.sent[0].embed
    assert embed is not None and embed.description is not None
    assert "Window: **`All time`**" in embed.description
    assert "Page: **`1`**" in embed.description
    assert "100" in embed.description
    assert "Year:" not in embed.description
    assert "Season:" not in embed.description


async def test_exp_lifetime_leaderboard_rejects_season_options(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    """Year/season belong to the seasonal window only — refuse them."""
    with pytest.raises(UserInputError):
        await invoke_command(
            Leaderboard(), ctx, mode="lifetime", year=2024
        )


async def test_lifetime_menu_pages_without_season_buttons(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The all-time pager keeps ◀/▶ and drops the ⬅/➡ season pair."""
    _stub_user_lookup(monkeypatch, {author.id: author})
    rows = [(i, 1000 + i, 500 - i) for i in range(1, 13)]
    menu = TopMenu(bot, cast(Any, ctx), None, rows, page=1, lifetime=True)
    assert len(cast(Any, menu)._rows[0]) == 2

    mctx = FakeMenuContext(FakeInteraction(id=1, member=author))
    await menu_button(menu, 1).callback(mctx)  # ▶

    embed = mctx.sent[0].embed
    assert embed is not None and embed.description is not None
    assert "Window: **`All time`**" in embed.description
    assert "Page: **`2`**" in embed.description


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
