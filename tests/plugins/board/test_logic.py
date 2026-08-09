"""Board plugin — pure logic tests: filtering, animation, hashing.

Week math is covered by ``tests/core/test_utils_weeks.py``.
"""

import io
from datetime import datetime, timezone

import pendulum
from PIL import Image

from plugins.board.logic import (
    MAX_IMAGES,
    build_post_content,
    content_sha256,
    in_week,
    is_animated,
    is_image_attachment,
)


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
