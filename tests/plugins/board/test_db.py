"""Board plugin — repository tests: dedup, week windows, pruning."""

from cazzubot.bot import CazzuBot
from plugins.board import db as board_db

_WEEK_START = "2026-08-02T00:00:00+00:00"
_WEEK_END = "2026-08-09T00:00:00+00:00"


async def _add(
    bot: CazzuBot,
    ts: str,
    *,
    url: str = "https://example.com/a.png",
    msg: str = "https://discord.com/channels/2/99/1",
    sha: str = "hash-a",
) -> bool:
    return await board_db.add_image(bot.db, ts, url, msg, sha)


async def test_add_image_ignores_repeat_url(bot: CazzuBot) -> None:
    assert await _add(bot, "2026-08-03T00:00:00+00:00")
    # same url (same message re-scraped) → ignored
    assert not await _add(bot, "2026-08-03T00:00:00+00:00")

    rows = await board_db.get_week_images(bot.db, _WEEK_START, _WEEK_END)
    assert len(rows) == 1
    assert rows[0].msg_url == "https://discord.com/channels/2/99/1"


async def test_has_sha_in_week_is_window_scoped(bot: CazzuBot) -> None:
    await _add(bot, "2026-08-03T00:00:00+00:00", sha="hash-a")
    assert await board_db.has_sha_in_week(
        bot.db, "hash-a", _WEEK_START, _WEEK_END
    )
    # the same image may reappear in a later week
    next_week = ("2026-08-09T00:00:00+00:00", "2026-08-16T00:00:00+00:00")
    assert not await board_db.has_sha_in_week(bot.db, "hash-a", *next_week)


async def test_get_week_images_ordered_and_windowed(bot: CazzuBot) -> None:
    await _add(bot, "2026-08-01T00:00:00+00:00", url="u0")  # before
    await _add(bot, "2026-08-03T00:00:00+00:00", url="u1")
    await _add(bot, "2026-08-04T00:00:00+00:00", url="u2")
    await _add(bot, "2026-08-10T00:00:00+00:00", url="u3")  # after

    rows = await board_db.get_week_images(bot.db, _WEEK_START, _WEEK_END)
    assert [r.image_url for r in rows] == ["u1", "u2"]


async def test_latest_ts_and_delete(bot: CazzuBot) -> None:
    assert await board_db.latest_ts(bot.db) is None
    await _add(bot, "2026-08-04T00:00:00+00:00", url="u2")
    await _add(bot, "2026-08-03T00:00:00+00:00", url="u1")
    assert await board_db.latest_ts(bot.db) == "2026-08-04T00:00:00+00:00"

    rows = await board_db.get_week_images(bot.db, _WEEK_START, _WEEK_END)
    await board_db.delete_image(bot.db, rows[0].id)
    remaining = await board_db.get_week_images(
        bot.db, _WEEK_START, _WEEK_END
    )
    assert [r.image_url for r in remaining] == ["u2"]
