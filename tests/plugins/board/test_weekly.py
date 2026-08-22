"""Board plugin — weekly automation tests.

``run_weekly`` (the shared scrape → poll → grid flow), its done-guard,
the guild-side target selection, and the ``board_weekly`` scheduler
handler / cadence arming. ``seeded_bot`` provides the booted bot with
fake cache/rest wired in; ``weekly._download_url`` is stubbed.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io

import pendulum
from PIL import Image

from cazzubot import utils
from cazzubot.bot import CazzuBot
from plugins.board import (
    CADENCE,
    BoardPlugin,
    on_board_weekly_close,
    on_board_weekly_due,
)
from plugins.board import weekly
from plugins.board.weekly import (
    CLOSE_TAG,
    DONE_KEY,
    MESSAGE_OPEN,
    POLL_DESC,
    POLL_TITLE,
    POST_CHANNEL_DEV,
    POST_CHANNEL_PROD,
    SCRAPE_CHANNEL_DEV,
    SCRAPE_CHANNEL_PROD,
    VOTE_ROLE_ID,
    run_weekly,
    weekly_targets,
)
from plugins.poll import db as poll_db
from tests.fakes import FakeAttachment, FakeMessage, rest_of


def _bytes_for(url: str) -> bytes:
    """Distinct PNG bytes per url (same-length urls must not collide)."""
    buf = io.BytesIO()
    color = (
        int(hashlib.sha256(url.encode()).hexdigest()[0:2], 16),
        int(hashlib.sha256(url.encode()).hexdigest()[2:4], 16),
        int(hashlib.sha256(url.encode()).hexdigest()[4:6], 16),
    )
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


async def _fake_download_url(url: str) -> bytes:
    return _bytes_for(url)


def _seed_week(
    bot: CazzuBot,
    *,
    channel_id: int,
    week: int = 1,
    count: int = 3,
) -> None:
    """Seed ``count`` image messages ``week`` weeks before this one
    (week=1 = last week, matching the production default)."""
    start = utils.week_start(pendulum.now("UTC")).subtract(days=7 * week)
    inside = start.add(hours=12)
    rest = rest_of(bot)
    for i in range(count):
        rest.messages[(channel_id, i + 1)] = FakeMessage(
            id=i + 1,
            channel_id=channel_id,
            created_at=inside.add(hours=i),
            attachments=[
                FakeAttachment(
                    id=i + 1,
                    filename=f"img{i}.png",
                    url=f"https://example.com/img{i}.png",
                )
            ],
        )


def test_weekly_targets_production() -> None:
    assert weekly_targets("production") == (
        SCRAPE_CHANNEL_PROD,
        POST_CHANNEL_PROD,
        False,
    )


def test_weekly_targets_development() -> None:
    assert weekly_targets("development") == (
        SCRAPE_CHANNEL_DEV,
        POST_CHANNEL_DEV,
        True,
    )


async def test_run_weekly_full_flow_dev(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    """Scrape the current week → poll + grid + MESSAGE_OPEN in the dev
    post channel, poll open with n items and max_vote = n // 20 + 1."""
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot
    now = pendulum.now("UTC")
    _seed_week(bot, channel_id=SCRAPE_CHANNEL_DEV, week=0, count=3)

    result = await run_weekly(bot)

    assert not result.aborted
    assert result.scraped == 3
    assert result.poll_id is not None
    week_no, year = utils.week_number(utils.week_start(now))
    assert result.week_label == f"{year}-W{week_no:02}"

    poll_row = await poll_db.get_poll(bot.db, result.poll_id)
    assert poll_row is not None
    assert poll_row.title == POLL_TITLE.format(week_no=week_no)
    assert poll_row.description == POLL_DESC
    assert poll_row.max_vote == 1  # 3 // 20 + 1
    assert poll_row.open == 1
    assert len(await poll_db.get_items(bot.db, result.poll_id)) == 3

    created = rest_of(bot).created
    assert len(created) == 1  # announcement + grid + poll in one message
    msg = created[0]
    assert msg.channel_id == POST_CHANNEL_DEV
    assert msg.embeds  # the poll embed
    content = msg.content
    assert content.startswith(
        MESSAGE_OPEN.format(role_id=VOTE_ROLE_ID, week_no=week_no)
    )
    assert f"Week {week_no} — 3 image(s)" in content
    assert (
        f"[1](https://discord.com/channels/2/{SCRAPE_CHANNEL_DEV}/1)"
        in content
    )
    # the <@&VOTE_ROLE_ID> opener must actually ping — hikari's default
    # allowed_mentions is {"parse": []}
    assert msg.create_kwargs is not None
    assert msg.create_kwargs["role_mentions"] is True
    assert msg.create_kwargs["user_mentions"] is True
    assert poll_row.mid == msg.id
    assert poll_row.cid == POST_CHANNEL_DEV
    assert await bot.settings.get(DONE_KEY) == result.week_label


async def test_run_weekly_guard_skips_and_force_reruns(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot
    _seed_week(bot, channel_id=SCRAPE_CHANNEL_DEV, week=0, count=2)

    first = await run_weekly(bot)
    assert not first.aborted

    second = await run_weekly(bot)
    assert second.aborted
    assert "already done" in second.reason
    assert await bot.db.fetchval("SELECT COUNT(*) FROM poll") == 1
    assert len(rest_of(bot).created) == 1

    forced = await run_weekly(bot, force=True)
    assert not forced.aborted
    assert await bot.db.fetchval("SELECT COUNT(*) FROM poll") == 2


async def test_run_weekly_empty_week_aborts(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot

    result = await run_weekly(bot)

    assert result.aborted
    assert "No images" in result.reason
    assert await bot.db.fetchval("SELECT COUNT(*) FROM poll") == 0
    assert rest_of(bot).created == []
    assert await bot.settings.get(DONE_KEY, "") == ""


async def test_run_weekly_samples_over_max_images(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    """A 60-image week samples down to MAX_IMAGES grid cells/poll items."""
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot
    _seed_week(bot, channel_id=SCRAPE_CHANNEL_DEV, week=0, count=60)

    result = await run_weekly(bot)

    assert not result.aborted
    assert result.scraped == 50
    assert result.poll_id is not None
    poll_row = await poll_db.get_poll(bot.db, result.poll_id)
    assert poll_row is not None
    assert poll_row.max_vote == 3  # 50 // 20 + 1
    assert len(await poll_db.get_items(bot.db, result.poll_id)) == 50
    assert "50 image(s)" in rest_of(bot).created[0].content


async def test_run_weekly_production_last_week_prod_channels(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    """guild_kind=production → last week's window + the prod channels."""
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot
    bot.config = dataclasses.replace(bot.config, guild_kind="production")
    _seed_week(bot, channel_id=SCRAPE_CHANNEL_PROD, week=1, count=2)

    result = await run_weekly(bot)

    assert not result.aborted
    week_no, year = utils.week_number(
        utils.week_start(pendulum.now("UTC")).subtract(days=7)
    )
    assert result.week_label == f"{year}-W{week_no:02}"
    assert [m.channel_id for m in rest_of(bot).created] == [
        POST_CHANNEL_PROD
    ]
    assert result.poll_id is not None
    poll_row = await poll_db.get_poll(bot.db, result.poll_id)
    assert poll_row is not None
    assert poll_row.title == POLL_TITLE.format(week_no=week_no)


# -- scheduler wiring --------------------------------------------------------


async def test_on_board_weekly_due_rearms(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    """Even an aborted fire (empty week) re-arms the next Sunday."""
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot

    await on_board_weekly_due(bot, {})

    rows = await bot.scheduler.get("board_weekly")
    assert len(rows) == 1
    assert rows[0].run_at > pendulum.now("UTC")
    assert rows[0].payload.get("retry") is True


async def test_board_on_load_arms_when_rowless(bot: CazzuBot) -> None:
    await BoardPlugin().on_load(bot)
    rows = await bot.scheduler.get("board_weekly")
    assert len(rows) == 1
    assert rows[0].run_at > pendulum.now("UTC")
    assert rows[0].payload.get("retry") is True


async def test_board_on_load_leaves_existing_row(bot: CazzuBot) -> None:
    run_at = pendulum.now("UTC").add(days=2)
    await bot.scheduler.add("board_weekly", run_at)
    await BoardPlugin().on_load(bot)
    rows = await bot.scheduler.get("board_weekly")
    assert len(rows) == 1
    assert rows[0].run_at == run_at


def test_cadence_is_sunday_midnight() -> None:
    now = pendulum.datetime(2026, 8, 13, 12, 0, tz="UTC")  # a Thursday
    nxt = CADENCE.next_run(now)
    assert nxt.day_of_week == pendulum.SUNDAY
    assert (nxt.hour, nxt.minute) == (0, 0)
    assert nxt > now


# -- close + winner ----------------------------------------------------------


async def test_run_weekly_schedules_monday_close(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    """The open poll auto-closes 24h later (Monday 00:00 UTC)."""
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot
    now = pendulum.now("UTC")
    _seed_week(bot, channel_id=SCRAPE_CHANNEL_DEV, week=0, count=2)

    result = await run_weekly(bot)

    rows = await bot.scheduler.get(CLOSE_TAG)
    assert len(rows) == 1
    task = rows[0]
    assert task.payload["pid"] == result.poll_id
    assert task.payload["cid"] == POST_CHANNEL_DEV
    assert task.payload["retry"] is True
    assert pendulum.parse(str(task.payload["start"])) is not None
    assert task.run_at >= now.add(days=1).start_of("minute")


async def test_board_weekly_close_resolves_winner(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    """Close: poll flag off + button removed; winner → guild banner + msg."""
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot
    _seed_week(bot, channel_id=SCRAPE_CHANNEL_DEV, week=0, count=3)
    result = await run_weekly(bot)
    assert result.poll_id is not None
    await poll_db.add_votes(bot.db, result.poll_id, [1, 1, 1], 424242)
    rows = await bot.scheduler.get(CLOSE_TAG)
    assert len(rows) == 1

    rest = rest_of(bot)
    rest.created.clear()
    await on_board_weekly_close(bot, rows[0].payload)

    poll_row = await poll_db.get_poll(bot.db, result.poll_id)
    assert poll_row is not None and poll_row.open == 0
    # the vote button was removed from the poll message
    assert rest.edited and rest.edited[-1][1]["component"] is None
    # the winning image became the guild banner
    assert len(rest.guild_edits) == 1
    assert "banner" in rest.guild_edits[0][1]
    # winner announcement in the post channel, linking the original message
    assert rest.created and rest.created[-1].channel_id == POST_CHANNEL_DEV
    winner_msg = rest.created[-1].content or ""
    assert "# Week" in winner_msg
    assert "https://discord.com/channels/2/" in winner_msg


async def test_board_weekly_close_no_votes(
    seeded_bot: CazzuBot, monkeypatch
) -> None:
    """No votes → a no-votes message and no banner change."""
    monkeypatch.setattr(weekly, "_download_url", _fake_download_url)
    bot = seeded_bot
    _seed_week(bot, channel_id=SCRAPE_CHANNEL_DEV, week=0, count=2)
    result = await run_weekly(bot)
    assert result.poll_id is not None
    rows = await bot.scheduler.get(CLOSE_TAG)
    assert len(rows) == 1

    rest = rest_of(bot)
    rest.created.clear()
    await on_board_weekly_close(bot, rows[0].payload)

    assert rest.guild_edits == []  # no winner → no banner change
    last = rest.created[-1].content or ""
    assert "no votes" in last
