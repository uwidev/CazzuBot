"""Board plugin — pure logic tests: filtering, animation, hashing, and the
scrape/grid services (fake rest + injected downloaders).

Week math is covered by ``tests/core/test_utils_weeks.py``.
"""

import hashlib
import io
from datetime import datetime, timezone

import pendulum
from PIL import Image

from cazzubot import utils
from cazzubot.bot import CazzuBot
from plugins.board import db as board_db
from plugins.board.logic import (
    MAX_IMAGES,
    build_grid,
    build_post_content,
    content_sha256,
    in_week,
    is_animated,
    is_image_attachment,
    scrape_week,
)
from tests.fakes import FakeAttachment, FakeMember, FakeMessage, FakeRest


def test_in_week_window_is_half_open() -> None:
    start = pendulum.datetime(2026, 8, 9, tz="UTC")
    end = start.add(days=7)
    inside = datetime(2026, 8, 15, 23, 59, tzinfo=timezone.utc)
    at_end = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    before = datetime(2026, 8, 8, 23, 59, tzinfo=timezone.utc)
    assert in_week(inside, start, end)
    assert not in_week(at_end, start, end)
    assert not in_week(before, start, end)


def test_is_image_attachment() -> None:
    assert is_image_attachment("image/png")
    assert is_image_attachment("image/gif")
    assert not is_image_attachment("video/mp4")
    assert not is_image_attachment("text/plain")
    assert not is_image_attachment(None)
    assert not is_image_attachment("")


# -- animation filtering -----------------------------------------------------


def _gif_bytes(animated: bool) -> bytes:
    buf = io.BytesIO()
    frames = [
        Image.new("RGB", (8, 8), (255, 0, 0)),
        Image.new("RGB", (8, 8), (0, 255, 0)),
    ]
    if animated:
        frames[0].save(
            buf,
            "GIF",
            save_all=True,
            append_images=frames[1:],
            duration=50,
            loop=0,
        )
    else:
        frames[0].save(buf, "GIF")
    return buf.getvalue()


def test_is_animated_detects_multi_frame_gif() -> None:
    assert is_animated(_gif_bytes(animated=True))


def test_is_animated_single_frame_gif_is_static() -> None:
    assert not is_animated(_gif_bytes(animated=False))


def test_is_animated_png_is_static() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, "PNG")
    assert not is_animated(buf.getvalue())


def test_is_animated_garbage_is_not_animated() -> None:
    assert not is_animated(b"not an image")


def test_content_sha256_is_hex_and_deterministic() -> None:
    digest = content_sha256(b"hello")
    assert len(digest) == 64
    assert digest == content_sha256(b"hello")
    assert digest != content_sha256(b"hello!")


def test_max_images_cap() -> None:
    assert MAX_IMAGES == 50


# -- post content ------------------------------------------------------------


def test_build_post_content_links_on_own_line() -> None:
    content = build_post_content("Header", ["u1", "u2"])
    assert content == "Header\n[1](u1) [2](u2)"


def test_build_post_content_no_marker_when_all_fit() -> None:
    content = build_post_content("Header", ["u1", "u2"])
    assert not content.endswith(" …")


def test_build_post_content_truncates_tail_with_marker() -> None:
    urls = [
        f"https://discord.com/channels/2/99/{1000 + i}" for i in range(50)
    ]
    content = build_post_content("Header", urls)
    assert len(content) <= 2000
    assert content.endswith(" …")
    assert "[1](https://discord.com/channels/2/99/1000)" in content


def test_build_post_content_never_overflows_with_marker() -> None:
    """The marker is gated on the remaining budget (regression: it used
    to push content past the limit when links landed within a char)."""
    urls = [
        f"https://discord.com/channels/2/99/{1000 + i}" for i in range(60)
    ]
    for header_len in (0, 1, 50, 1900, 1950, 1990, 1999):
        content = build_post_content("H" * header_len, urls)
        assert len(content) <= 2000, header_len


# -- scrape_week service -----------------------------------------------------


def _png_bytes(color: tuple[int, int, int] = (10, 200, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


async def _png_download(url: str) -> bytes:
    """Distinct PNG bytes per url (same-length urls must not collide)."""
    digest = hashlib.sha256(url.encode()).hexdigest()
    return _png_bytes(
        (
            int(digest[0:2], 16),
            int(digest[2:4], 16),
            int(digest[4:6], 16),
        )
    )


def _seed_messages(
    rest: FakeRest,
    *,
    channel_id: int = 99,
    start: pendulum.DateTime,
    count: int = 3,
) -> None:
    """Seed ``count`` image messages at start+1h … start+count h."""
    for i in range(count):
        rest.messages[(channel_id, i + 1)] = FakeMessage(
            id=i + 1,
            author=FakeMember(id=1, name="a"),
            channel_id=channel_id,
            created_at=start.add(hours=i + 1),
            attachments=[
                FakeAttachment(
                    id=i + 1,
                    filename=f"img{i}.png",
                    url=f"https://example.com/img{i}.png",
                )
            ],
        )


async def test_scrape_week_records_window_images(bot: CazzuBot) -> None:
    rest = FakeRest()
    start = utils.week_start(pendulum.now("UTC")).subtract(days=7)
    end = start.add(days=7)
    _seed_messages(rest, channel_id=99, start=start)

    result = await scrape_week(
        rest,
        bot.db,
        guild_id=2,
        channel_id=99,
        start=start,
        end=end,
        download=_png_download,
    )

    assert result.scraped == 3
    assert result.skipped_animated == 0
    assert result.skipped_duplicates == 0
    rows = await board_db.get_week_images(
        bot.db, start.isoformat(), end.isoformat()
    )
    assert len(rows) == 3
    assert [r.msg_url for r in rows] == [
        f"https://discord.com/channels/2/99/{i}" for i in (1, 2, 3)
    ]


async def test_scrape_week_skips_animated_and_out_of_window(
    bot: CazzuBot,
) -> None:
    rest = FakeRest()
    start = utils.week_start(pendulum.now("UTC")).subtract(days=7)
    end = start.add(days=7)
    _seed_messages(rest, channel_id=99, start=start)
    rest.messages[(99, 9)] = FakeMessage(
        id=9,
        author=FakeMember(id=1, name="a"),
        channel_id=99,
        created_at=start.add(hours=5),
        attachments=[
            FakeAttachment(
                id=9,
                filename="anim.gif",
                media_type="image/gif",
                url="https://example.com/anim.gif",
            )
        ],
    )
    rest.messages[(99, 10)] = FakeMessage(
        id=10,
        author=FakeMember(id=1, name="a"),
        channel_id=99,
        created_at=end.add(hours=1),
        attachments=[
            FakeAttachment(
                id=10,
                filename="late.png",
                media_type="image/png",
                url="https://example.com/late.png",
            )
        ],
    )

    async def _download(url: str) -> bytes:
        if url.endswith("anim.gif"):
            buf = io.BytesIO()
            frames = [
                Image.new("RGB", (4, 4), (255, 0, 0)),
                Image.new("RGB", (4, 4), (0, 255, 0)),
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
        return await _png_download(url)

    result = await scrape_week(
        rest, bot.db, 2, 99, start, end, download=_download
    )

    assert result.scraped == 3
    assert result.skipped_animated == 1
    # the out-of-window image is never counted at all
    assert result.skipped_duplicates == 0


async def test_scrape_week_dedupes_same_bytes_in_window(
    bot: CazzuBot,
) -> None:
    """The same image re-posted in another message takes one grid slot."""
    rest = FakeRest()
    start = utils.week_start(pendulum.now("UTC")).subtract(days=7)
    end = start.add(days=7)
    _seed_messages(rest, channel_id=99, start=start)
    rest.messages[(99, 9)] = FakeMessage(
        id=9,
        author=FakeMember(id=1, name="a"),
        channel_id=99,
        created_at=start.add(hours=6),
        attachments=[
            FakeAttachment(
                id=9,
                filename="dup.png",
                url="https://example.com/dup.png",
            )
        ],
    )

    async def _download(url: str) -> bytes:
        if url.endswith("dup.png"):
            # identical content to img0.png → a within-week duplicate
            return await _png_download("https://example.com/img0.png")
        return await _png_download(url)

    result = await scrape_week(
        rest, bot.db, 2, 99, start, end, download=_download
    )

    assert result.scraped == 3
    assert result.skipped_duplicates == 1


# -- build_grid service ------------------------------------------------------


async def _seed_rows(bot: CazzuBot, count: int = 3) -> list[board_db.BoardRow]:
    start = pendulum.datetime(2026, 8, 2, tz="UTC")
    for i in range(count):
        await board_db.add_image(
            bot.db,
            start.add(days=i).isoformat(),
            f"https://example.com/g{i}.png",
            f"https://discord.com/channels/2/99/{10 + i}",
            f"hash-{i}",
        )
    return await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat()
    )


async def test_build_grid_stitches_survivors(bot: CazzuBot) -> None:
    rows = await _seed_rows(bot)

    result = await build_grid(
        bot.db,
        rows,
        download=_png_download,
        day="2026-08-09",
        columns=2,
        cell_size=64,
    )

    assert result.pruned == 0
    assert len(result.survivors) == 3
    assert result.content.startswith(
        "Week 2026-08-09 — 3 image(s) · 2 cols · 64px"
    )
    assert "[1](https://discord.com/channels/2/99/10)" in result.content
    assert isinstance(result.data, bytes) and result.data
    # 3 images in 2 columns → 2 rows; label area 96px, 8px borders
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.size == (2 * 64 + 8, 2 * (64 + 96) + 8)


async def test_build_grid_prunes_dead_rows(bot: CazzuBot) -> None:
    start = pendulum.datetime(2026, 8, 2, tz="UTC")
    await board_db.add_image(
        bot.db,
        start.isoformat(),
        "https://example.com/ok.png",
        "https://discord.com/channels/2/99/1",
        "hash-ok",
    )
    await board_db.add_image(
        bot.db,
        start.add(hours=1).isoformat(),
        "https://example.com/dead.png",
        "https://discord.com/channels/2/99/2",
        "hash-dead",
    )
    rows = await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat()
    )

    async def _download(url: str) -> bytes:
        if url.endswith("dead.png"):
            raise RuntimeError("gone")
        return _png_bytes()

    result = await build_grid(bot.db, rows, download=_download, day="2026-08-09")

    assert result.pruned == 1
    assert len(result.survivors) == 1
    assert "1 image(s)" in result.content
    remaining = await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat()
    )
    assert [r.image_url for r in remaining] == ["https://example.com/ok.png"]


async def test_build_grid_all_dead_returns_empty(bot: CazzuBot) -> None:
    start = pendulum.datetime(2026, 8, 2, tz="UTC")
    await board_db.add_image(
        bot.db,
        start.isoformat(),
        "https://example.com/dead.png",
        "https://discord.com/channels/2/99/1",
        "hash",
    )
    rows = await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat()
    )

    async def _download(_url: str) -> bytes:
        raise RuntimeError("gone")

    result = await build_grid(bot.db, rows, download=_download, day="2026-08-09")

    assert result.survivors == []
    assert result.data == b""
    assert result.content == ""
