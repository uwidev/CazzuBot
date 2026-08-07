"""Fun plugin — member/echo commands, inktober reaction, story write."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import pytest
from discord.ext import commands

from cazzubot.bot import CazzuBot
from plugins.fun import (
    EchoCog,
    InktoberCog,
    MemberCog,
    StoryCog,
)
from tests.fakes import FakeChannel, FakeContext, FakeMember, FakeMessage

_CogT = TypeVar("_CogT", bound=commands.Cog)


def _cog_of(bot: CazzuBot, cog_type: type[_CogT]) -> _CogT:
    name = getattr(cog_type, "__cog_name__")
    assert isinstance(name, str)
    cog = bot.get_cog(name)
    assert isinstance(cog, cog_type)
    return cog


async def test_member_commands(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    member = _cog_of(bot, MemberCog)
    await member.hashiresoriyo(ctx)
    assert ctx.sent[-1].content is not None
    assert "youtube.com" in ctx.sent[-1].content
    await member.noot(ctx)
    assert ctx.sent[-1].content == "NOOT NOOT"
    await member.info(ctx, member=author)
    assert ctx.sent[-1].content == (
        f"{author} joined on {author.joined_at} and has 0 roles"
    )


async def test_echo(bot: CazzuBot, ctx: FakeContext) -> None:
    await _cog_of(bot, EchoCog).echo(ctx, content="hello!")
    assert ctx.sent[-1].content == "hello!"


async def test_inktober_reacts_to_valid_submission(
    bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await bot.settings.set("inktober.cid", channel.id)
    message = FakeMessage(
        id=1,
        content="Inktober day 3 submission",
        author=author,
        channel=channel,
    )
    message.attachments = [object()]
    await _cog_of(bot, InktoberCog).on_message(message)
    assert message.reactions == ["👍"]


async def test_inktober_ignores_non_submissions(
    bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await bot.settings.set("inktober.cid", channel.id)
    message = FakeMessage(
        id=1, content="just chatting", author=author, channel=channel
    )
    await _cog_of(bot, InktoberCog).on_message(message)
    assert message.reactions == []


async def test_register_inktober_sets_channel(
    bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    await _cog_of(bot, InktoberCog).register_inktober(ctx, channel=channel)
    assert await bot.settings.get("inktober.cid") == channel.id
    assert (
        ctx.sent[-1].content
        == f"✓ Inktober channel set to <#{channel.id}>"
    )


async def test_story_compile_writes_files(
    bot: CazzuBot,
    ctx: FakeContext,
    channel: FakeChannel,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    channel.messages.append(
        FakeMessage(id=1, content="once upon", author=author)
    )
    channel.messages.append(
        FakeMessage(id=2, content="a time", author=author)
    )

    await _cog_of(bot, StoryCog).story_compile(ctx)

    story = (tmp_path / "story" / "general.txt").read_text()
    assert story == "once upon a time "
    contrib = (tmp_path / "story" / "general-contributors.txt").read_text()
    assert "Total contributions: 2" in contrib
    assert ctx.message.deleted is True  # prefix invocation cleans up


async def test_story_write_headers_and_cleans_up(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await _cog_of(bot, StoryCog).story_write(ctx, "missing")
    assert ctx.sent[-1].content == "```fix\n>>> missing <<<```"
    assert ctx.message.deleted is True
