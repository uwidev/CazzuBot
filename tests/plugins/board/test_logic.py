"""Board plugin — pure logic tests: filtering, animation, hashing, and the
scrape/grid services (fake rest + injected downloaders).

Week math is covered by ``tests/core/test_utils_weeks.py``.
"""

import hashlib
import io
import random
from datetime import datetime, timezone

import pendulum
from PIL import Image

from core import utils
from core.bot import CazzuBot
from plugins.board import db as board_db
from plugins.board.logic import (
    MAX_IMAGES,
    _encode_upload,
    _webp_bytes,
    build_grid,
    build_post_pages,
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


def test_build_post_pages_links_on_own_line() -> None:
    pages = build_post_pages("Header", ["u1", "u2"])
    assert pages == ["Header\n[1](u1) [2](u2)"]


def test_build_post_pages_empty_urls_keeps_header_only() -> None:
    assert build_post_pages("Header", []) == ["Header"]


def test_build_post_pages_splits_without_dropping_links() -> None:
    """A week bigger than the content limit spills onto more messages —
    every link survives, in order, and no page exceeds the limit."""
    urls = [
        f"https://discord.com/channels/2/99/{1000 + i}" for i in range(50)
    ]
    pages = build_post_pages("Header", urls)

    assert len(pages) > 1
    assert all(len(page) <= 2000 for page in pages)
    joined = " ".join(pages)
    for i, url in enumerate(urls, 1):
        assert f"[{i}]({url})" in joined
    # first page opens with the header, later pages mark the continuation
    assert pages[0].startswith("Header\n")
    assert pages[1].startswith("Header — continued\n")


def test_build_post_pages_never_overflows() -> None:
    """Regression: the old truncating builder could push content past the
    limit on the marker; pagination must hold for any header length."""
    urls = [
        f"https://discord.com/channels/2/99/{1000 + i}" for i in range(60)
    ]
    for header_len in (0, 1, 50, 1900, 1950, 1990, 1999):
        pages = build_post_pages("H" * header_len, urls)
        assert all(len(page) <= 2000 for page in pages), header_len


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
        bot.db, start.isoformat(), end.isoformat(), 99
    )
    assert len(rows) == 3
    assert [r.msg_url for r in rows] == [
        f"https://discord.com/channels/2/99/{i}" for i in (1, 2, 3)
    ]
    # every row records its source channel + message (board v2)
    assert [r.channel_id for r in rows] == [99, 99, 99]
    assert [r.message_id for r in rows] == [1, 2, 3]


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


async def test_scrape_week_same_content_other_channel_not_duplicate(
    bot: CazzuBot,
) -> None:
    """board v2: the same image bytes in ANOTHER channel the same week is
    not a false duplicate — within-week dedup is per-channel."""
    rest = FakeRest()
    start = utils.week_start(pendulum.now("UTC")).subtract(days=7)
    end = start.add(days=7)
    _seed_messages(rest, channel_id=99, start=start)
    # channel 88 re-posts img0's exact bytes (distinct CDN url)
    rest.messages[(88, 1)] = FakeMessage(
        id=1,
        author=FakeMember(id=1, name="a"),
        channel_id=88,
        created_at=start.add(hours=1),
        attachments=[
            FakeAttachment(
                id=1,
                filename="x.png",
                url="https://example.com/88/x.png",
            )
        ],
    )

    async def _download(url: str) -> bytes:
        if url.endswith("88/x.png"):
            # identical content to channel 99's img0
            return await _png_download("https://example.com/img0.png")
        return await _png_download(url)

    await scrape_week(rest, bot.db, 2, 99, start, end, download=_download)
    result = await scrape_week(
        rest, bot.db, 2, 88, start, end, download=_download
    )

    # the same content in a fresh channel is NOT skipped as a duplicate
    assert result.scraped == 1
    assert result.skipped_duplicates == 0
    other = await board_db.get_week_images(
        bot.db, start.isoformat(), end.isoformat(), 88
    )
    assert len(other) == 1
    assert other[0].channel_id == 88
    # re-scraping the SAME channel still dedupes (per-channel window)
    again = await scrape_week(
        rest, bot.db, 2, 88, start, end, download=_download
    )
    assert again.scraped == 0
    assert again.skipped_duplicates == 1


# -- build_grid service ------------------------------------------------------


async def _seed_rows(
    bot: CazzuBot, count: int = 3
) -> list[board_db.BoardRow]:
    start = pendulum.datetime(2026, 8, 2, tz="UTC")
    for i in range(count):
        await board_db.add_image(
            bot.db,
            # hours, not days: a count past 7 must stay inside the week
            start.add(hours=i).isoformat(),
            f"https://example.com/g{i}.png",
            f"https://discord.com/channels/2/99/{10 + i}",
            f"hash-{i}",
            99,
            10 + i,
        )
    return await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat(), 99
    )


# -- upload sizing -----------------------------------------------------------


def _noisy_canvas(size: tuple[int, int] = (768, 768)) -> Image.Image:
    """A noise canvas — worst case for WebP (nothing compresses)."""
    random.seed(1)
    image = Image.new("RGB", size)
    image.putdata(
        [
            (
                random.randrange(256),
                random.randrange(256),
                random.randrange(256),
            )
            for _ in range(size[0] * size[1])
        ]
    )
    return image


def test_encode_upload_downscales_to_fit_the_cap() -> None:
    """The guard re-encodes (quality, then resolution) until the bytes fit
    the cap — proven on a noise canvas against a proportional cap, because
    a real 50-cell grid (3872×8712) takes ~1min to encode and would make
    the suite unusable. Verified separately: that grid is ~21MB at q85,
    i.e. well over Discord's 8MB cap, and encodes to 7.0MB under it."""
    canvas = _noisy_canvas((512, 512))
    cap = len(_webp_bytes(canvas, 85)) // 8  # 8× smaller than the source
    assert cap < len(_webp_bytes(canvas, 85))

    data = _encode_upload(canvas, cap)

    assert len(data) <= cap
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "WEBP"
        assert image.size[0] <= 512  # traded resolution, never upscaled


def test_encode_upload_keeps_small_incompressible_image() -> None:
    """A grid already under the cap is returned as-is (no needless loss)."""
    canvas = _noisy_canvas((256, 256))
    data = _encode_upload(canvas)
    assert data == _webp_bytes(canvas, 85)


async def test_build_grid_stitches_survivors(bot: CazzuBot) -> None:
    rows = await _seed_rows(bot)

    result = await build_grid(
        bot.db,
        rows,
        download=_png_download,
        week=33,
        columns=2,
        cell_size=64,
    )

    assert result.pruned == 0
    assert len(result.survivors) == 3
    assert len(result.pages) == 1
    page = result.pages[0]
    assert page.content.startswith("Week 33 — 3 image(s)")
    assert "[1](https://discord.com/channels/2/99/10)" in page.content
    assert isinstance(page.data, bytes) and page.data
    # 3 images in 2 columns → 2 rows; label area 96px, 8px borders
    with Image.open(io.BytesIO(page.data)) as image:
        assert image.size == (2 * 64 + 8, 2 * (64 + 96) + 8)


async def test_build_grid_splits_over_max_images(bot: CazzuBot) -> None:
    """More rows than MAX_IMAGES → several grid images, links complete on
    the leading page(s) and the images last."""
    total = MAX_IMAGES + 5
    rows = await _seed_rows(bot, count=total)

    result = await build_grid(
        bot.db,
        rows,
        download=_png_download,
        week=33,
        columns=5,
        cell_size=32,
    )

    assert len(result.survivors) == total
    # the image pages are paginated and always come last
    imaged = [p for p in result.pages if p.data]
    assert len(imaged) == 2
    assert result.pages[-1] is imaged[-1]  # last message carries a grid
    # every link survives across the messages
    numbers = [
        n
        for page in result.pages
        for n in range(1, total + 1)
        if f"[{n}](" in page.content
    ]
    assert sorted(set(numbers)) == list(range(1, total + 1))
    # the first image shares the LAST link page; the second labels itself
    assert f"Week 33 — {total} image(s)" in imaged[0].content
    assert "[55](" in imaged[0].content  # the tail links ride the image
    assert "[1](" in result.pages[0].content  # the head links lead
    assert imaged[1].content == "Grid 2/2 — 51–55"


async def test_build_grid_prunes_dead_rows(bot: CazzuBot) -> None:
    start = pendulum.datetime(2026, 8, 2, tz="UTC")
    await board_db.add_image(
        bot.db,
        start.isoformat(),
        "https://example.com/ok.png",
        "https://discord.com/channels/2/99/1",
        "hash-ok",
        99,
        1,
    )
    await board_db.add_image(
        bot.db,
        start.add(hours=1).isoformat(),
        "https://example.com/dead.png",
        "https://discord.com/channels/2/99/2",
        "hash-dead",
        99,
        2,
    )
    rows = await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat(), 99
    )

    async def _download(url: str) -> bytes:
        if url.endswith("dead.png"):
            raise RuntimeError("gone")
        return _png_bytes()

    result = await build_grid(bot.db, rows, download=_download, week=33)

    assert result.pruned == 1
    assert len(result.survivors) == 1
    assert len(result.pages) == 1
    assert "1 image(s)" in result.pages[0].content
    remaining = await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat(), 99
    )
    assert [r.image_url for r in remaining] == [
        "https://example.com/ok.png"
    ]


async def test_build_grid_all_dead_returns_empty(bot: CazzuBot) -> None:
    start = pendulum.datetime(2026, 8, 2, tz="UTC")
    await board_db.add_image(
        bot.db,
        start.isoformat(),
        "https://example.com/dead.png",
        "https://discord.com/channels/2/99/1",
        "hash",
        99,
        1,
    )
    rows = await board_db.get_week_images(
        bot.db, start.isoformat(), start.add(days=7).isoformat(), 99
    )

    async def _download(_url: str) -> bytes:
        raise RuntimeError("gone")

    result = await build_grid(bot.db, rows, download=_download, week=33)

    assert result.survivors == []
    assert result.pages == []
