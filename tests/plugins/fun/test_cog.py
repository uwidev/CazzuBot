"""Fun plugin — member/echo commands, inktober reaction, story write."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from cazzubot.bot import CazzuBot
from plugins.fun.cog import (
    Echo,
    Hashiresoriyo,
    Info,
    Noot,
    RegisterInktober,
    StoryCompile,
    StoryWrite,
    on_message,
)
from tests.fakes import (
    rest_of,
    FakeChannel,
    FakeContext,
    FakeMember,
    FakeMessage,
    FakeMessageCreateEvent,
    invoke_command,
)


async def test_member_commands(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await invoke_command(Hashiresoriyo(), ctx)
    assert ctx.sent[-1].content is not None
    assert "youtube.com" in ctx.sent[-1].content
    await invoke_command(Noot(), ctx)
    assert ctx.sent[-1].content == "NOOT NOOT"
    await invoke_command(Info(), ctx, member=author)
    assert ctx.sent[-1].content == (
        f"{author} joined on {author.joined_at} and has 0 roles"
    )


async def test_echo(bot: CazzuBot, ctx: FakeContext) -> None:
    await invoke_command(Echo(), ctx, content="hello!")
    assert ctx.sent[-1].content == "hello!"


async def test_inktober_reacts_to_valid_submission(
    seeded_bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await seeded_bot.settings.set("inktober.cid", channel.id)
    message = FakeMessage(
        id=1,
        content="Inktober day 3 submission",
        author=author,
        guild_id=2,
        channel_id=channel.id,
    )
    message.attachments = [object()]
    await on_message(
        cast(Any, FakeMessageCreateEvent(message=message, app=seeded_bot))
    )
    assert rest_of(seeded_bot).reactions == [(channel.id, 1, "👍")]


async def test_inktober_ignores_other_guild(
    seeded_bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    """A submission in the OTHER guild never gets the inktober reaction."""
    await seeded_bot.settings.set("inktober.cid", channel.id)
    message = FakeMessage(
        id=1,
        content="Inktober day 3 submission",
        author=author,
        guild_id=999,
        channel_id=channel.id,
    )
    message.attachments = [object()]
    await on_message(
        cast(Any, FakeMessageCreateEvent(message=message, app=seeded_bot))
    )
    assert rest_of(seeded_bot).reactions == []


async def test_inktober_ignores_non_submissions(
    seeded_bot: CazzuBot, channel: FakeChannel, author: FakeMember
) -> None:
    await seeded_bot.settings.set("inktober.cid", channel.id)
    message = FakeMessage(
        id=1,
        content="just chatting",
        author=author,
        guild_id=2,
        channel_id=channel.id,
    )
    await on_message(
        cast(Any, FakeMessageCreateEvent(message=message, app=seeded_bot))
    )
    assert rest_of(seeded_bot).reactions == []


async def test_register_inktober_sets_channel(
    bot: CazzuBot, ctx: FakeContext, channel: FakeChannel
) -> None:
    await invoke_command(RegisterInktober(), ctx, channel=channel)
    assert await bot.settings.get("inktober.cid") == channel.id
    assert (
        ctx.sent[-1].content
        == f"✓ Inktober channel set to <#{channel.id}>"
    )


async def test_story_compile_writes_files(
    seeded_bot: CazzuBot,
    ctx: FakeContext,
    channel: FakeChannel,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    rest_of(seeded_bot).messages[(channel.id, 1)] = FakeMessage(
        id=1, content="once upon", author=author, channel_id=channel.id
    )
    rest_of(seeded_bot).messages[(channel.id, 2)] = FakeMessage(
        id=2, content="a time", author=author, channel_id=channel.id
    )

    await invoke_command(StoryCompile(), ctx)

    story = (tmp_path / "story" / "general.txt").read_text()
    assert story == "once upon a time "
    contrib = (tmp_path / "story" / "general-contributors.txt").read_text()
    assert "Total contributions: 2" in contrib
    assert ctx.edits[-1]["content"].startswith("Compiled 2 contributions")


async def test_story_write_headers(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await invoke_command(StoryWrite(), ctx, file_name="missing")
    assert ctx.sent[-1].content == "```fix\n>>> missing <<<```"
