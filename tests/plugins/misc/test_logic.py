"""Misc plugin — banner image prep + snowflake decode tests."""

import io

import pendulum
from PIL import Image

from plugins.misc.logic import (
    MessageLink,
    parse_message_link,
    prepare_banner,
    snowflake_time,
)


def _png_bytes(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 80, 200)).save(buf, "PNG")
    return buf.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_banner_crops_tall_image_to_16_9() -> None:
    # 4:3 → crop the height: 400 x (400 / (16/9))
    out = prepare_banner(_png_bytes((400, 300)))
    assert _open(out).size == (400, 225)


def test_banner_crops_wide_image_to_16_9() -> None:
    # 21:9 → crop the width: (900 * 16/9) x 900
    out = prepare_banner(_png_bytes((2100, 900)))
    assert _open(out).size == (1600, 900)


def test_banner_downscales_large_16_9() -> None:
    out = prepare_banner(_png_bytes((4000, 2250)))
    assert _open(out).size == (1920, 1080)


def test_banner_keeps_small_images() -> None:
    out = prepare_banner(_png_bytes((320, 180)))
    assert _open(out).size == (320, 180)


def test_banner_returns_jpeg_bytes() -> None:
    out = prepare_banner(_png_bytes((400, 300)))
    assert out.startswith(b"\xff\xd8")  # JPEG SOI marker
    assert _open(out).format == "JPEG"


# -- snowflake decoding ------------------------------------------------------


def test_snowflake_time_at_discord_epoch() -> None:
    # id 1 = the first possible snowflake, right at the Discord epoch
    assert snowflake_time(1) == pendulum.datetime(2015, 1, 1, tz="UTC")


def test_snowflake_time_known_id() -> None:
    # 2^44 >> 22 = 2^22 ms after the epoch: 2015-01-01 01:09:54.304 UTC
    assert snowflake_time(17592186044416) == pendulum.datetime(
        2015, 1, 1, 1, 9, 54, 304000, tz="UTC"
    )


def test_snowflake_time_millisecond_precision() -> None:
    mid = 1529019173215272960
    when = snowflake_time(mid)
    created_ms = (mid >> 22) + 1420070400000
    assert (
        when.int_timestamp * 1000 + when.microsecond // 1000 == created_ms
    )


# -- message link parsing ----------------------------------------------------


def test_parse_message_link() -> None:
    link = parse_message_link(
        "https://discord.com/channels/2/99/1535535252141768744"
    )
    assert link == MessageLink(
        guild_id="2", channel_id=99, message_id=1535535252141768744
    )


def test_parse_message_link_accepts_query_and_app_host() -> None:
    link = parse_message_link(
        "https://discordapp.com/channels/@me/99/1?app=desktop"
    )
    assert link == MessageLink(guild_id="@me", channel_id=99, message_id=1)


def test_parse_message_link_rejects_non_links() -> None:
    for text in (
        "1535535252141768744",
        "https://discord.com/channels/2/99",
        "https://example.com/channels/2/99/1",
        "https://discord.com/invite/abc",
        "",
    ):
        assert parse_message_link(text) is None, text
