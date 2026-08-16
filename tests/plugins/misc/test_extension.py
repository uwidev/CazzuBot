# pyright: reportArgumentType=false
"""Misc plugin — command tests: banner + welcome screen through the extension."""

from __future__ import annotations

import io

import hikari
from PIL import Image

from cazzubot.bot import CazzuBot
from tests.fakes import (
    FakeAttachment,
    FakeChannel,
    FakeContext,
    FakeMember,
    FakeMessage,
    invoke_command,
    rest_of,
)
from typing import cast


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (10, 200, 40)).save(buf, "PNG")
    return buf.getvalue()


async def _fake_download(_attachment: FakeAttachment) -> bytes:
    return _png_bytes()


def _ctx(
    bot: CazzuBot, member: FakeMember, channel: FakeChannel, guild
) -> FakeContext:
    return FakeContext(
        bot=bot, member=member, guild=guild, channel=channel
    )


def _deny(*_args, **_kwargs):
    raise hikari.UnauthorizedError(
        "https://example.com", {}, None, "missing permissions"
    )


async def test_banner_sets_guild_banner(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    from plugins.misc import extension as misc_ext

    monkeypatch.setattr(misc_ext, "_download", _fake_download)
    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    image = FakeAttachment(filename="pic.png", media_type="image/png")

    await invoke_command(misc_ext.Banner(), ctx, image=image)

    assert len(rest_of(seeded_bot).guild_edits) == 1
    gid, kwargs = rest_of(seeded_bot).guild_edits[0]
    assert gid == 2
    banner = cast(hikari.Bytes, kwargs["banner"])
    assert banner.filename == "banner.jpg"
    assert isinstance(banner.data, bytes)
    assert banner.data.startswith(b"\xff\xd8")  # JPEG
    assert "Server banner updated" in (ctx.sent[-1].content or "")


async def test_banner_reports_missing_permission(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    from plugins.misc import extension as misc_ext

    monkeypatch.setattr(misc_ext, "_download", _fake_download)
    monkeypatch.setattr(rest_of(seeded_bot), "edit_guild", _deny)
    ctx = _ctx(seeded_bot, author, channel, fake_guild)

    await invoke_command(misc_ext.Banner(), ctx, image=FakeAttachment())

    assert "MANAGE_GUILD" in (ctx.sent[-1].content or "")


async def test_banner_from_message_link(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    """msg uses the first image attachment on that message."""
    from plugins.misc import extension as misc_ext

    monkeypatch.setattr(misc_ext, "_download", _fake_download)
    rest = rest_of(seeded_bot)
    rest.messages[(99, 1)] = FakeMessage(
        id=1,
        channel_id=99,
        attachments=[
            FakeAttachment(id=1, filename="v.mp4", media_type="video/mp4"),
            FakeAttachment(
                id=2, filename="pic.png", media_type="image/png"
            ),
        ],
    )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(
        misc_ext.Banner(),
        ctx,
        msg="https://discord.com/channels/2/99/1",
    )

    assert len(rest_of(seeded_bot).guild_edits) == 1
    banner = rest_of(seeded_bot).guild_edits[0][1]["banner"]
    assert isinstance(banner, hikari.Bytes)
    assert "Server banner updated" in (ctx.sent[-1].content or "")


async def test_banner_message_has_no_images(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    rest = rest_of(seeded_bot)
    rest.messages[(99, 1)] = FakeMessage(
        id=1, channel_id=99, attachments=[]
    )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(
        misc_ext.Banner(),
        ctx,
        msg="https://discord.com/channels/2/99/1",
    )

    assert "no image attachments" in (ctx.sent[-1].content or "")


async def test_banner_message_missing(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(
        misc_ext.Banner(),
        ctx,
        msg="https://discord.com/channels/2/99/1",
    )

    assert "no longer exists" in (ctx.sent[-1].content or "")


async def test_banner_msg_wins_over_image(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    from plugins.misc import extension as misc_ext

    monkeypatch.setattr(misc_ext, "_download", _fake_download)
    rest = rest_of(seeded_bot)
    rest.messages[(99, 1)] = FakeMessage(
        id=1,
        channel_id=99,
        attachments=[
            FakeAttachment(
                id=2, filename="pic.png", media_type="image/png"
            )
        ],
    )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(
        misc_ext.Banner(),
        ctx,
        msg="https://discord.com/channels/2/99/1",
        image=FakeAttachment(filename="other.png"),
    )

    # one edit, driven by the message's image, not the attached one
    assert len(rest_of(seeded_bot).guild_edits) == 1
    assert "Server banner updated" in (ctx.sent[-1].content or "")


async def test_banner_requires_image_or_msg(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(misc_ext.Banner(), ctx)

    assert "Provide an image or a msg" in (ctx.sent[-1].content or "")


async def test_welcome_edits_screen(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(
        misc_ext.Welcome(),
        ctx,
        enabled=True,
        description="Welcome to Club Cirno!",
    )

    assert rest_of(seeded_bot).welcome_screen_edits == [
        (
            2,
            {
                "enabled": True,
                "description": "Welcome to Club Cirno!",
                "channels": hikari.UNDEFINED,
            },
        )
    ]
    assert "Welcome screen updated" in (ctx.sent[-1].content or "")


async def test_welcome_enabled_only(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(misc_ext.Welcome(), ctx, enabled=False)

    assert rest_of(seeded_bot).welcome_screen_edits == [
        (
            2,
            {
                "enabled": False,
                "description": hikari.UNDEFINED,
                "channels": hikari.UNDEFINED,
            },
        )
    ]


async def test_welcome_sets_featured_channel(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(
        misc_ext.Welcome(),
        ctx,
        enabled=True,
        channel=FakeChannel(id=77, name="rules"),
    )

    _gid, kwargs = rest_of(seeded_bot).welcome_screen_edits[0]
    assert kwargs == {
        "enabled": True,
        "description": hikari.UNDEFINED,
        "channels": [hikari.WelcomeChannel(channel_id=77, description="")],
    }


async def test_welcome_missing_screen_reports(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    from plugins.misc import extension as misc_ext

    def _not_found(*_args, **_kwargs):
        raise hikari.NotFoundError(
            "https://example.com", {}, None, "not set up"
        )

    monkeypatch.setattr(
        rest_of(seeded_bot), "edit_welcome_screen", _not_found
    )
    ctx = _ctx(seeded_bot, author, channel, fake_guild)

    await invoke_command(misc_ext.Welcome(), ctx, enabled=True)

    assert "no welcome screen set up" in (ctx.sent[-1].content or "")


# -- week --------------------------------------------------------------------


async def test_week_current_default(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(misc_ext.Week(), ctx)

    flushed = ctx.sent[-1].content or ""
    assert "It's " in flushed
    assert "weeks start sunday" in flushed


async def test_week_monday_start(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(misc_ext.Week(), ctx, start="monday")

    assert "weeks start monday" in (ctx.sent[-1].content or "")


async def test_week_message_link(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    """id 1 → 2015-01-01 (Thursday) → Sunday-start week 52 of 2014."""
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(
        misc_ext.Week(),
        ctx,
        msg="https://discord.com/channels/2/99/1",
    )

    flushed = ctx.sent[-1].content or ""
    assert "Message 1 (posted 2015-01-01 00:00 UTC)" in flushed
    assert "— https://discord.com/channels/2/99/1" in flushed
    assert "is in 2014-W52 (weeks start sunday)" in flushed


async def test_week_large_message_link(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    """Full-size snowflakes work through a message link (no API calls)."""
    from plugins.misc import extension as misc_ext

    mid = 1535535252141768744
    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(
        misc_ext.Week(),
        ctx,
        msg=f"https://discord.com/channels/2/99/{mid}",
    )

    flushed = ctx.sent[-1].content or ""
    assert f"Message {mid} (posted 2026-08-08 06:28 UTC)" in flushed
    assert f"— https://discord.com/channels/2/99/{mid}" in flushed
    assert "is in 2026-W31 (weeks start sunday)" in flushed


async def test_week_invalid_message_link(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.misc import extension as misc_ext

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(misc_ext.Week(), ctx, msg="1535535252141768744")

    flushed = ctx.sent[-1].content or ""
    assert "msg must be a Discord message link" in flushed
