"""Experience cog tests — the canonical controller-layer example.

Invokes the live loaded cog's command methods with a fake context and asserts
on recorded sends + resulting DB state. Checks (is_owner / has_permissions)
are bypassed by direct invocation — those get dedicated dispatch-level tests.
"""

from __future__ import annotations

from typing import cast

import discord
import pytest
import pendulum
from discord.ext import commands

from cazzubot.bot import CazzuBot
from plugins.experience import db as exp_db
from plugins.experience.cog import ExperienceCog, TopView
from tests.fakes import (
    FakeChannel,
    FakeContext,
    FakeInteraction,
    FakeMember,
    FakeUser,
)

_AUTHOR_ID = 424242


def _cog(bot: CazzuBot) -> ExperienceCog:
    cog = bot.get_cog(ExperienceCog.__cog_name__)
    assert isinstance(cog, ExperienceCog)
    return cog


async def _seed_exp(bot: CazzuBot, uid: int, amount: int) -> None:
    """Give ``uid`` ``amount`` lifetime/seasonal exp (via the exp logs)."""
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, uid)
    await exp_db.add_exp_log(bot.db, uid, amount, now)
    await exp_db.sync_with_exp_logs(bot.db)


def _stub_user_lookup(
    bot: CazzuBot,
    monkeypatch: pytest.MonkeyPatch,
    users: dict[int, FakeMember | FakeUser],
) -> None:
    """Make utils.find_user resolve from a dict (no fetch_user network)."""

    def _resolve(uid: int) -> FakeMember | FakeUser | None:
        return users.get(uid)

    monkeypatch.setattr(bot, "get_user", _resolve)


async def test_exp_no_experience_embed(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    cog = _cog(bot)
    await cog.exp(ctx, user=author)
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
    _stub_user_lookup(
        bot, monkeypatch, {author.id: author, other.id: other}
    )
    await _seed_exp(bot, author.id, 100)
    await _seed_exp(bot, other.id, 50)

    cog = _cog(bot)
    await cog.exp(ctx, user=author)

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
    cog = _cog(bot)
    with pytest.raises(commands.BadArgument):
        await cog.exp_top(ctx, season=99)


def _make_view(bot: CazzuBot, ctx: FakeContext) -> TopView:
    rows = [(1, ctx.author.id, 100)]
    return TopView(
        _cog(bot), ctx, pendulum.datetime(2026, 1, 1), rows, page=1
    )


async def test_topview_denies_foreign_user(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    view = _make_view(bot, ctx)
    foreign = FakeMember(id=999, name="other", guild=ctx.guild)
    interaction = FakeInteraction(id=1, user=foreign, guild=ctx.guild)
    button = view.children[2]
    assert button.callback is not None
    await button.callback(interaction)
    assert interaction.response.calls == [
        (
            "send_message",
            {
                "content": "This leaderboard is not yours to page.",
                "ephemeral": True,
            },
        )
    ]


async def test_topview_pages_for_author(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_user_lookup(bot, monkeypatch, {author.id: author})
    view = _make_view(bot, ctx)
    interaction = FakeInteraction(id=1, user=author, guild=ctx.guild)
    button = view.children[2]
    assert button.callback is not None
    await button.callback(interaction)
    assert interaction.response.calls[0][0] == "edit_message"
    embed = cast(discord.Embed, interaction.response.calls[0][1]["embed"])
    # one row -> max page is 1 -> next_page stays on page 1
    assert embed.description is not None
    assert "Page: **`1`**" in embed.description


async def test_quiet_add_then_warn(
    bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    cog = _cog(bot)
    await cog.quiet_add(ctx, channel)
    assert ctx.sent[-1].content == "✓ Added <#99> to the quiet list"
    assert await bot.settings.get("level.quiet") == [99]

    await cog.quiet_add(ctx, channel)
    assert ctx.sent[-1].content == "⚠︎ Channel already in the quiet list"
