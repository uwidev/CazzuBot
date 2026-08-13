"""Counter plugin tests — baka button, re-create, expiry handler."""

from __future__ import annotations

from typing import Any, cast

import pendulum

from cazzubot import utils
from cazzubot.bot import CazzuBot
from plugins.counter.cog import (
    NO_BAKAS_TEXT,
    _handle_baka,
    on_counter_expire,
    on_interaction,
)
from plugins.counter.cog import Create
from plugins.counter import db as counter_db
from tests.fakes import (
    rest_of,
    FakeCache,
    FakeChannel,
    FakeComponentInteraction,
    FakeContext,
    FakeMember,
    FakeMessage,
    invoke_command,
)

_MID = 555


async def test_baka_press_ignored_for_other_guild(
    bot: CazzuBot, author: FakeMember
) -> None:
    """A button press in the OTHER guild never counts (dev bot in prod)."""
    from types import SimpleNamespace

    interaction = FakeComponentInteraction(
        user=author, custom_id="counter:baka", guild_id=999
    )
    await on_interaction(
        cast(Any, SimpleNamespace(interaction=interaction, app=bot))
    )

    assert interaction.responses == []
    assert await bot.db.fetchval("SELECT COUNT(*) FROM counter_event") == 0


async def test_counter_expiry_ignores_other_guild_channel(
    seeded_bot: CazzuBot, fake_cache: FakeCache
) -> None:
    """An expiry armed for the other guild's channel never edits it."""
    other = FakeChannel(id=777, name="other", guild_id=999)
    fake_cache.add_channel(other)

    await on_counter_expire(seeded_bot, {"mid": _MID, "cid": other.id})

    assert rest_of(seeded_bot).edited == []


async def test_counter_create_makes_message_and_row(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await invoke_command(Create(), ctx)
    assert ctx.sent[0].embed is not None
    row = await bot.db.fetchone(
        "SELECT id, mid FROM counter WHERE mid = 1"
    )
    assert row is not None and row["id"] == 1
    assert await bot.db.fetchval("SELECT COUNT(*) FROM counter_event") == 0


async def test_counter_create_with_id_recreates_deleted_counter(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    # a counter whose message was deleted: registered row + historical events
    counter_id = await counter_db.create(bot.db, _MID)
    await counter_db.record_event(
        bot.db, counter_id, 1, "cirno", "2026-01-01T00:00:00+00:00"
    )

    await invoke_command(Create(), ctx, counter_id=counter_id)

    # same unique id, but the mid now points at the new message
    assert (
        await bot.db.fetchval(
            "SELECT mid FROM counter WHERE id = ?", counter_id
        )
    ) == 1
    assert (
        await bot.db.fetchval(
            "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
            counter_id,
        )
        == 1
    )
    # the new message's embed already carries the preserved count
    assert ctx.sent[0].embed is not None
    assert ctx.sent[0].embed.description == "> 1"


async def test_counter_create_unknown_id_errors(
    ctx: FakeContext,
) -> None:
    from cazzubot.errors import UserInputError

    try:
        await invoke_command(Create(), ctx, counter_id=999)
    except UserInputError as err:
        assert "999" in str(err)
    else:
        raise AssertionError(
            "expected UserInputError for unknown counter id"
        )


async def test_baka_press_appends_event_and_schedules(
    bot: CazzuBot, author: FakeMember
) -> None:
    counter_id = await counter_db.create(bot.db, _MID)
    interaction = FakeComponentInteraction(user=author, message_id=_MID)

    await _handle_baka(bot, interaction)

    assert (
        await bot.db.fetchval(
            "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
            counter_id,
        )
        == 1
    )
    event = await bot.db.fetchone(
        "SELECT uid, name FROM counter_event WHERE counter_id = ?",
        counter_id,
    )
    assert event is not None
    assert event["uid"] == author.id
    assert event["name"] == "cirno"
    tasks = await bot.scheduler.get("counter")
    assert len(tasks) == 1
    assert tasks[0].payload == {"mid": _MID, "cid": 99}
    response_type, _payload = interaction.responses[0]
    assert response_type.name == "MESSAGE_UPDATE"


async def test_baka_press_denies_unknown_message(
    bot: CazzuBot, author: FakeMember
) -> None:
    interaction = FakeComponentInteraction(user=author, message_id=999)

    await _handle_baka(bot, interaction)

    assert (
        await bot.db.fetchone("SELECT id FROM counter WHERE mid = 999")
        is None
    )
    assert await bot.scheduler.get("counter") == []
    response_type, payload = interaction.responses[0]
    assert response_type.name == "MESSAGE_CREATE"
    assert payload["content"] == "This is not a baka counter anymore."


async def test_counter_expiry_resets_footer_keeps_events(
    seeded_bot: CazzuBot, channel: FakeChannel
) -> None:
    message = FakeMessage(
        id=_MID,
        content="",
        guild_id=2,
        channel_id=channel.id,
        embeds=[utils.prepare_embed("baka", "> 3")],
    )
    rest_of(seeded_bot).messages[(channel.id, _MID)] = message
    counter_id = await counter_db.create(seeded_bot.db, _MID)
    await counter_db.record_event(
        seeded_bot.db,
        counter_id,
        1,
        "cirno",
        pendulum.now("UTC").to_iso8601_string(),
    )

    await on_counter_expire(seeded_bot, {"mid": _MID, "cid": channel.id})

    # the history survives the footer reset
    assert (
        await seeded_bot.db.fetchval(
            "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
            counter_id,
        )
        == 1
    )
    assert message.embeds[0].footer is not None
    assert message.embeds[0].footer.text == NO_BAKAS_TEXT
    assert len(rest_of(seeded_bot).edited) == 1
