"""Counter plugin tests — baka button, expiry handler."""

from __future__ import annotations

import pendulum

from cazzubot import utils
from cazzubot.bot import CazzuBot
from plugins.counter.cog import (
    NO_BAKAS_TEXT,
    _handle_baka,
    on_counter_expire,
)
from plugins.counter.cog import Create
from tests.fakes import (
    rest_of,
    FakeChannel,
    FakeComponentInteraction,
    FakeContext,
    FakeMember,
    FakeMessage,
    invoke_command,
)

_MID = 555


async def test_counter_create_makes_message_and_row(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await invoke_command(Create(), ctx)
    assert ctx.sent[0].embed is not None
    row = await bot.db.fetchone("SELECT count FROM counter WHERE mid = 1")
    assert row is not None and row["count"] == 0


async def test_baka_press_increments_and_schedules(
    bot: CazzuBot, author: FakeMember
) -> None:
    await bot.db.execute(
        "INSERT OR IGNORE INTO counter (mid, count) VALUES (?, 0)", _MID
    )
    interaction = FakeComponentInteraction(user=author, message_id=_MID)

    await _handle_baka(bot, interaction)

    assert (
        await bot.db.fetchval(
            "SELECT count FROM counter WHERE mid = ?", _MID
        )
        == 1
    )
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
        await bot.db.fetchval("SELECT count FROM counter WHERE mid = 999")
        is None
    )
    assert await bot.scheduler.get("counter") == []
    response_type, payload = interaction.responses[0]
    assert response_type.name == "MESSAGE_CREATE"
    assert payload["content"] == "This is not a baka counter anymore."


async def test_counter_expiry_resets_footer(
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
    await seeded_bot.db.execute(
        "INSERT OR IGNORE INTO counter (mid, count) VALUES (?, 0)", _MID
    )
    await seeded_bot.db.execute(
        "INSERT INTO counter_baka (mid, uid, name, updated_at) VALUES (?, ?, ?, ?)",
        _MID,
        1,
        "cirno",
        pendulum.now("UTC").to_iso8601_string(),
    )

    await on_counter_expire(seeded_bot, {"mid": _MID, "cid": channel.id})

    assert (
        await seeded_bot.db.fetchval(
            "SELECT COUNT(*) FROM counter_baka WHERE mid = ?", _MID
        )
        == 0
    )
    assert message.embeds[0].footer is not None
    assert message.embeds[0].footer.text == NO_BAKAS_TEXT
    assert len(rest_of(seeded_bot).edited) == 1
