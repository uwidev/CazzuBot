# pyright: reportArgumentType=false
"""Board plugin — command tests: scrape + post through the real cog."""

from __future__ import annotations

import io

import hikari
import pendulum
import pytest
from PIL import Image

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from plugins.board import db
from tests.fakes import (
    FakeAttachment,
    FakeChannel,
    FakeContext,
    FakeMember,
    FakeMessage,
    invoke_command,
    rest_of,
)
# one distinct color per attachment url, so hashes differ
_COLORS = {
    "https://example.com/a.png": (10, 200, 40),
    "https://example.com/b.png": (200, 10, 40),
    "https://example.com/c.gif": (40, 40, 200),
}
_ANIMATED_URL = "https://example.com/anim.gif"
_DUP_URL = "https://example.com/dup.png"  # same bytes as a.png
_DEAD_URL = "https://example.com/dead.png"  # download always fails


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(buf, "PNG")
    return buf.getvalue()


def _animated_gif_bytes() -> bytes:
    buf = io.BytesIO()
    frames = [
        Image.new("RGB", (80, 60), (255, 0, 0)),
        Image.new("RGB", (80, 60), (0, 255, 0)),
    ]
    frames[0].save(
        buf,
        "GIF",
        save_all=True,
        append_images=frames[1:],
        duration=50,
        loop=0,
    )
    return buf.getvalue()


async def _fake_download_url(url: str) -> bytes:
    if url == _DEAD_URL:
        raise hikari.NotFoundError(
            "https://example.com", {}, None, "message deleted"
        )
    if url == _ANIMATED_URL:
        return _animated_gif_bytes()
    if url == _DUP_URL:
        return _png_bytes(_COLORS["https://example.com/a.png"])
    return _png_bytes(_COLORS.get(url, (10, 200, 40)))


def _ctx(
    bot: CazzuBot,
    member: FakeMember,
    channel,
    guild,
) -> FakeContext:
    return FakeContext(
        bot=bot, member=member, guild=guild, channel=channel
    )


def _seed_messages(
    rest, author: FakeMember, now, *, week: int = 1
) -> None:
    """Seed messages in the week ``week`` weeks before this one.

    The scrape default is last week (this week − 1), so week=1 (default)
    puts messages in the window a default scrape collects.
    """
    start = utils.week_start(now, start="sunday").subtract(days=7 * week)
    inside = start.add(hours=12)
    rest.messages = {
        (99, 1): FakeMessage(
            id=1,
            author=author,
            channel_id=99,
            created_at=inside.add(hours=1),
            attachments=[
                FakeAttachment(
                    id=1, filename="a.png", url="https://example.com/a.png"
                )
            ],
        ),
        (99, 2): FakeMessage(
            id=2,
            author=author,
            channel_id=99,
            created_at=inside.add(hours=2),
            attachments=[
                FakeAttachment(
                    id=2, filename="b.png", url="https://example.com/b.png"
                ),
                FakeAttachment(
                    id=3,
                    filename="c.gif",
                    media_type="image/gif",
                    url="https://example.com/c.gif",
                ),
                FakeAttachment(
                    id=4,
                    filename="d.mp4",
                    media_type="video/mp4",
                    url="https://example.com/d.mp4",
                ),
                # animated GIF — downloaded, then skipped as non-static
                FakeAttachment(
                    id=6,
                    filename="anim.gif",
                    media_type="image/gif",
                    url=_ANIMATED_URL,
                ),
            ],
        ),
        # outside the scrape week — must be ignored
        (99, 3): FakeMessage(
            id=3,
            author=author,
            channel_id=99,
            created_at=start.subtract(days=1),
            attachments=[
                FakeAttachment(
                    id=5,
                    filename="old.png",
                    url="https://example.com/old.png",
                )
            ],
        ),
    }


async def test_scrape_saves_rows(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    _seed_messages(rest, author, now)

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Scrape(), ctx)

    start = utils.week_start(now, start="sunday").subtract(days=7)
    end = start.add(days=7)
    rows = await db.get_week_images(
        seeded_bot.db, start.isoformat(), end.isoformat()
    )
    assert [(r.image_url, r.msg_url) for r in rows] == [
        (
            "https://example.com/a.png",
            "https://discord.com/channels/2/99/1",
        ),
        (
            "https://example.com/b.png",
            "https://discord.com/channels/2/99/2",
        ),
        (
            "https://example.com/c.gif",
            "https://discord.com/channels/2/99/2",
        ),
    ]
    message = rest.messages[(99, 1)]
    assert rows[0].ts == pendulum.instance(message.created_at).isoformat()
    assert len(rows[0].sha256) == 64

    flushed = ctx.sent[-1].content or ""
    assert "Scraped 3 new image(s)" in flushed
    assert "Skipped 1 animated image(s)" in flushed


async def test_scrape_dedupes_on_second_run(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    _seed_messages(rest, author, now)
    ctx = _ctx(seeded_bot, author, channel, fake_guild)

    await invoke_command(board_cog.Scrape(), ctx)
    ctx.sent.clear()
    await invoke_command(board_cog.Scrape(), ctx)

    flushed = ctx.sent[-1].content or ""
    assert "Scraped 0 new image(s)" in flushed
    assert "Skipped 3 duplicate image(s)" in flushed


async def test_scrape_same_image_new_message_is_duplicate(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    """The same image re-posted in another message takes one grid slot."""
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    _seed_messages(rest, author, now)
    start = utils.week_start(now, start="sunday").subtract(days=7)
    rest.messages[(99, 4)] = FakeMessage(
        id=4,
        author=author,
        channel_id=99,
        created_at=start.add(days=2),
        attachments=[
            FakeAttachment(id=7, filename="dup.png", url=_DUP_URL)
        ],
    )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Scrape(), ctx)

    flushed = ctx.sent[-1].content or ""
    assert "Scraped 3 new image(s)" in flushed
    assert "Skipped 1 duplicate image(s)" in flushed


async def test_scrape_week_argument_targets_that_week(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    """An explicit week scrapes that week, not the default (last week)."""
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    # seed the CURRENT week; the default scrape would look at last week
    _seed_messages(rest, author, now, week=0)
    current_week = utils.week_start(now, start="sunday").isocalendar()[1]

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Scrape(), ctx, week=current_week)

    start = utils.week_start(now, start="sunday")
    rows = await db.get_week_images(
        seeded_bot.db, start.isoformat(), start.add(days=7).isoformat()
    )
    assert len(rows) == 3
    flushed = ctx.sent[-1].content or ""
    assert f"for week {current_week}" in flushed


async def test_scrape_invalid_week_rejected(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    """Weeks outside 1-53 (or that don't exist) raise UserInputError."""
    from plugins.board import cog as board_cog

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    with pytest.raises(UserInputError):
        await invoke_command(board_cog.Scrape(), ctx, week=99)


async def test_post_uploads_grid_with_links(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    _seed_messages(rest, author, now)
    await invoke_command(
        board_cog.Scrape(), _ctx(seeded_bot, author, channel, fake_guild)
    )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Post(), ctx)

    sent = ctx.sent[-1]
    week_no = utils.week_number(
        utils.week_start(now, start="sunday").subtract(days=7)
    )[0]
    assert sent.embed is None  # plain content: text above the attachment
    content = sent.content or ""
    lines = content.splitlines()
    assert lines[0].startswith(f"Week {week_no} — ")
    assert lines[1].startswith("[1](https://discord.com/channels/2/99/1)")
    assert "3 image(s)" in content
    assert "cols" not in content and "px" not in content
    assert "[3](https://discord.com/channels/2/99/2)" in content
    assert isinstance(sent.attachment, hikari.Bytes)


async def test_post_custom_grid_args(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    """columns/cell_size flow through to the stitched grid geometry."""
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    _seed_messages(rest, author, now)
    await invoke_command(
        board_cog.Scrape(), _ctx(seeded_bot, author, channel, fake_guild)
    )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Post(), ctx, columns=2, cell_size=100)

    sent = ctx.sent[-1]
    # geometry flows through to the stitched grid (header shows no dims)
    data = sent.attachment.data
    assert isinstance(data, bytes)
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (2 * 100 + 8, 2 * (100 + 96) + 8)


async def test_post_prunes_dead_rows(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    """Rows whose image no longer downloads are deleted, not stitched."""
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    _seed_messages(rest, author, now)
    await invoke_command(
        board_cog.Scrape(), _ctx(seeded_bot, author, channel, fake_guild)
    )
    start = utils.week_start(now, start="sunday").subtract(days=7)
    await db.add_image(
        seeded_bot.db,
        start.add(days=2).isoformat(),
        _DEAD_URL,
        "https://discord.com/channels/2/99/99",
        "dead-hash",
    )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Post(), ctx)

    end = start.add(days=7)
    rows = await db.get_week_images(
        seeded_bot.db, start.isoformat(), end.isoformat()
    )
    assert all(r.image_url != _DEAD_URL for r in rows)
    assert len(rows) == 3
    flushed = "\n".join(s.content or "" for s in ctx.sent)
    assert "Deleted 1 row(s)" in flushed
    assert any("3 image(s)" in (s.content or "") for s in ctx.sent)


async def test_post_week_argument(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    """An explicit week posts that week instead of the most recent."""
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    # scrape the CURRENT week (explicitly); post defaults to most recent,
    # so this only proves the week arg drives the target
    _seed_messages(rest, author, now, week=0)
    current_week = utils.week_start(now, start="sunday").isocalendar()[1]
    await invoke_command(
        board_cog.Scrape(),
        _ctx(seeded_bot, author, channel, fake_guild),
        week=current_week,
    )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Post(), ctx, week=current_week)

    assert (ctx.sent[-1].content or "").startswith(
        f"Week {current_week} — 3 image(s)"
    )


async def test_post_invalid_week_rejected(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.board import cog as board_cog

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    with pytest.raises(UserInputError):
        await invoke_command(board_cog.Post(), ctx, week=99)


async def test_post_truncates_links_over_budget(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
) -> None:
    """50 links overflow the content limit — tail links are dropped."""
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    start = utils.week_start(pendulum.now("UTC")).subtract(days=7)
    for i in range(50):
        await db.add_image(
            seeded_bot.db,
            start.add(hours=i).isoformat(),
            f"https://example.com/bulk{i}.png",
            f"https://discord.com/channels/2/99/{1000 + i}",
            f"hash-{i}",
        )

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Post(), ctx, columns=5, cell_size=64)

    content = ctx.sent[-1].content
    assert content is not None
    assert len(content) <= 2000
    assert content.endswith(" …")


async def test_post_without_scrape_errors(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
) -> None:
    from plugins.board import cog as board_cog

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Post(), ctx)
    assert "Nothing scraped yet" in (ctx.sent[-1].content or "")


@pytest.mark.parametrize(
    "channel_arg", [None, pytest.param(FakeChannel(id=99), id="explicit")]
)
async def test_scrape_defaults_to_invoking_channel(
    seeded_bot: CazzuBot,
    fake_guild,
    author: FakeMember,
    channel,
    monkeypatch,
    channel_arg,
) -> None:
    """channel=None and channel=99 behave identically (same channel)."""
    from plugins.board import cog as board_cog

    monkeypatch.setattr(board_cog, "_download_url", _fake_download_url)
    rest = rest_of(seeded_bot)
    now = pendulum.now("UTC")
    _seed_messages(rest, author, now)

    ctx = _ctx(seeded_bot, author, channel, fake_guild)
    await invoke_command(board_cog.Scrape(), ctx, channel=channel_arg)

    assert "Scraped 3 new image(s)" in (ctx.sent[-1].content or "")


async def test_board_weekly_command_runs_flow_via_driver(
    full_bot: CazzuBot, monkeypatch
) -> None:
    """/board weekly runs the full flow through the real command pipeline
    (owner hook + window reporting + rest sends to the dev channels)."""
    from plugins.board import weekly as board_weekly
    from plugins.board.weekly import (
        POST_CHANNEL_DEV,
        SCRAPE_CHANNEL_DEV,
        VOTE_ROLE_ID,
    )
    from plugins.poll import db as poll_db
    from tests.driver import run_slash

    monkeypatch.setattr(board_weekly, "_download_url", _fake_download_url)
    rest = rest_of(full_bot)
    now = pendulum.now("UTC")
    start = utils.week_start(now, start="sunday")
    inside = start.add(hours=12)
    for i in range(2):
        rest.messages[(SCRAPE_CHANNEL_DEV, i + 1)] = FakeMessage(
            id=i + 1,
            channel_id=SCRAPE_CHANNEL_DEV,
            created_at=inside.add(hours=i),
            attachments=[
                FakeAttachment(
                    id=i + 1,
                    filename=f"img{i}.png",
                    url=f"https://example.com/img{i}.png",
                )
            ],
        )

    result = await run_slash(
        full_bot, "board weekly", user_id=1, username="owner"
    )

    assert result.exceptions == []
    assert result.responded
    created = rest.created
    assert len(created) == 1  # announcement + grid + poll in one message
    msg = created[0]
    assert msg.channel_id == POST_CHANNEL_DEV
    assert msg.embeds  # the poll embed
    assert f"<@&{VOTE_ROLE_ID}>" in msg.content  # role ping
    assert "just-cirno voting is now open!" in msg.content
    assert "Week " in msg.content and "image(s)" in msg.content
    poll_count = await full_bot.db.fetchval("SELECT COUNT(*) FROM poll")
    assert poll_count == 1
