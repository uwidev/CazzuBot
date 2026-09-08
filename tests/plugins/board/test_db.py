"""Board plugin — repository tests: dedup, week windows, pruning, and
the per-channel scoping of board v2 (one channel per week — every read
is week × channel, never an aggregate)."""

from core.bot import CazzuBot
from plugins.board import db as board_db

_WEEK_START = "2026-08-02T00:00:00+00:00"
_WEEK_END = "2026-08-09T00:00:00+00:00"


async def _add(
    bot: CazzuBot,
    ts: str,
    *,
    url: str = "https://example.com/a.png",
    channel: int = 99,
    message: int = 1,
    sha: str = "hash-a",
) -> bool:
    msg_url = f"https://discord.com/channels/2/{channel}/{message}"
    return await board_db.add_image(
        bot.db, ts, url, msg_url, sha, channel, message
    )


async def test_add_image_records_channel_and_message(
    bot: CazzuBot,
) -> None:
    assert await _add(
        bot, "2026-08-03T00:00:00+00:00", channel=99, message=7
    )
    rows = await board_db.get_week_images(
        bot.db, _WEEK_START, _WEEK_END, 99
    )
    assert len(rows) == 1
    assert rows[0].channel_id == 99
    assert rows[0].message_id == 7
    assert rows[0].msg_url == "https://discord.com/channels/2/99/7"


async def test_add_image_ignores_repeat_url(bot: CazzuBot) -> None:
    assert await _add(bot, "2026-08-03T00:00:00+00:00")
    # same url (same message re-scraped) → ignored
    assert not await _add(bot, "2026-08-03T00:00:00+00:00")

    rows = await board_db.get_week_images(
        bot.db, _WEEK_START, _WEEK_END, 99
    )
    assert len(rows) == 1
    assert rows[0].msg_url == "https://discord.com/channels/2/99/1"


async def test_has_sha_in_week_is_window_and_channel_scoped(
    bot: CazzuBot,
) -> None:
    await _add(bot, "2026-08-03T00:00:00+00:00", sha="hash-a")
    # same channel, same window → duplicate
    assert await board_db.has_sha_in_week(
        bot.db, "hash-a", _WEEK_START, _WEEK_END, 99
    )
    # the same image may reappear in a later week
    next_week = ("2026-08-09T00:00:00+00:00", "2026-08-16T00:00:00+00:00")
    assert not await board_db.has_sha_in_week(
        bot.db, "hash-a", *next_week, 99
    )
    # cross-channel content is NOT a false duplicate (board v2)
    assert not await board_db.has_sha_in_week(
        bot.db, "hash-a", _WEEK_START, _WEEK_END, 88
    )


async def test_get_week_images_is_week_cap_channel(bot: CazzuBot) -> None:
    await _add(bot, "2026-08-01T00:00:00+00:00", url="u0")  # before
    await _add(bot, "2026-08-03T00:00:00+00:00", url="u1")
    await _add(bot, "2026-08-04T00:00:00+00:00", url="u2")
    await _add(bot, "2026-08-10T00:00:00+00:00", url="u3")  # after
    # same window, another channel → never leaks into this channel's read
    await _add(bot, "2026-08-04T00:00:00+00:00", url="u9", channel=88)

    rows = await board_db.get_week_images(
        bot.db, _WEEK_START, _WEEK_END, 99
    )
    assert [r.image_url for r in rows] == ["u1", "u2"]

    other = await board_db.get_week_images(
        bot.db, _WEEK_START, _WEEK_END, 88
    )
    assert [r.image_url for r in other] == ["u9"]


async def test_latest_row_and_delete(bot: CazzuBot) -> None:
    assert await board_db.latest_row(bot.db) is None
    await _add(bot, "2026-08-03T00:00:00+00:00", url="u1", message=1)
    await _add(bot, "2026-08-04T00:00:00+00:00", url="u2", message=2)
    latest = await board_db.latest_row(bot.db)
    assert latest is not None
    assert latest.ts == "2026-08-04T00:00:00+00:00"
    # the newest row carries its source channel (the post "pointer")
    assert latest.channel_id == 99
    assert latest.message_id == 2

    rows = await board_db.get_week_images(
        bot.db, _WEEK_START, _WEEK_END, 99
    )
    await board_db.delete_image(bot.db, rows[0].id)
    remaining = await board_db.get_week_images(
        bot.db, _WEEK_START, _WEEK_END, 99
    )
    assert [r.image_url for r in remaining] == ["u2"]
