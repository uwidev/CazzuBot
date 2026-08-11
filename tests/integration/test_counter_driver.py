"""Counter plugin via the offline interaction driver.

These tests drive the real event pipeline: ``/counter create`` runs through
lightbulb's command pipeline, then the baka press goes through hikari's
deserializer, the event manager and the plugin's raw
``InteractionCreateEvent`` listener — the same path a real Discord click
takes, minus the network.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import hikari

from cazzubot.bot import CazzuBot
from plugins.counter import db as counter_db
from tests.driver import press_button, run_slash


async def test_counter_create_then_baka_press(full_bot: CazzuBot) -> None:
    result = await run_slash(full_bot, "counter create", user_id=424242)

    assert result.response_type == hikari.ResponseType.MESSAGE_CREATE
    assert result.first_response is not None
    assert "embed" in result.first_response
    mid = result.response_message_id
    assert mid is not None
    row = await full_bot.db.fetchone(
        "SELECT id FROM counter WHERE mid = ?", mid
    )
    assert row is not None

    press = await press_button(
        full_bot,
        custom_id="counter:baka",
        message_id=mid,
        user_id=424242,
    )

    assert press.exceptions == []
    assert press.response_type == hikari.ResponseType.MESSAGE_UPDATE
    counter_id = row["id"]
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
            counter_id,
        )
        == 1
    )
    tasks = await full_bot.scheduler.get("counter")
    assert len(tasks) == 1
    assert tasks[0].payload == {"mid": mid, "cid": 99}


async def test_baka_press_on_unknown_message(full_bot: CazzuBot) -> None:
    await counter_db.create(full_bot.db, 555)

    press = await press_button(
        full_bot,
        custom_id="counter:baka",
        message_id=999,
        user_id=424242,
    )

    assert press.exceptions == []
    assert press.response_type == hikari.ResponseType.MESSAGE_CREATE
    assert press.first_response is not None
    assert press.first_response["content"] == (
        "This is not a baka counter anymore."
    )


async def test_counter_recreate_keeps_count(full_bot: CazzuBot) -> None:
    """Deleting the message and re-creating the counter keeps the count."""
    first = await run_slash(full_bot, "counter create", user_id=424242)
    mid = first.response_message_id
    assert mid is not None
    row = await full_bot.db.fetchone(
        "SELECT id FROM counter WHERE mid = ?", mid
    )
    assert row is not None
    counter_id = row["id"]

    await press_button(
        full_bot, custom_id="counter:baka", message_id=mid, user_id=424242
    )
    await press_button(
        full_bot, custom_id="counter:baka", message_id=mid, user_id=7
    )

    # the message is gone from discord; re-create the counter by its id
    recreated = await run_slash(
        full_bot,
        "counter create",
        options={"counter_id": counter_id},
        user_id=424242,
    )
    new_mid = recreated.response_message_id
    assert new_mid is not None and new_mid != mid

    assert (
        await full_bot.db.fetchval(
            "SELECT mid FROM counter WHERE id = ?", counter_id
        )
        == new_mid
    )
    # both presses survived the re-create — the count is the history
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
            counter_id,
        )
        == 2
    )
    assert recreated.first_response is not None
    assert recreated.first_response["embed"].description == "> 2"

    # the fresh message's button works
    press = await press_button(
        full_bot,
        custom_id="counter:baka",
        message_id=new_mid,
        user_id=424242,
    )
    assert press.exceptions == []
    assert press.response_type == hikari.ResponseType.MESSAGE_UPDATE
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
            counter_id,
        )
        == 3
    )


async def test_counter_survives_restart(
    full_bot: CazzuBot, tmp_path: Path
) -> None:
    """The persistent button keeps working after a full reboot on the
    same database — the manual H2 scenario."""
    from tests.conftest import boot_full_bot

    first = await run_slash(full_bot, "counter create", user_id=424242)
    mid = first.response_message_id
    assert mid is not None

    await full_bot._on_stopping(  # pyright: ignore[reportPrivateUsage]
        hikari.StoppingEvent(app=full_bot)
    )
    second = await boot_full_bot(tmp_path)

    try:
        press = await press_button(
            second,
            custom_id="counter:baka",
            message_id=mid,
            user_id=424242,
        )
        assert press.exceptions == []
        assert press.response_type == hikari.ResponseType.MESSAGE_UPDATE
        row = await second.db.fetchone(
            "SELECT id FROM counter WHERE mid = ?", mid
        )
        assert row is not None
        assert (
            await second.db.fetchval(
                "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
                row["id"],
            )
            == 1
        )
    finally:
        await second._on_stopping(  # pyright: ignore[reportPrivateUsage]
            hikari.StoppingEvent(app=second)
        )


async def test_baka_concurrent_presses_no_lost_updates(
    full_bot: CazzuBot,
) -> None:
    """Two simultaneous presses must both count (one event each)."""
    result = await run_slash(full_bot, "counter create", user_id=424242)
    mid = result.response_message_id
    assert mid is not None
    row = await full_bot.db.fetchone(
        "SELECT id FROM counter WHERE mid = ?", mid
    )
    assert row is not None
    counter_id = row["id"]

    presses = await asyncio.gather(
        press_button(
            full_bot,
            custom_id="counter:baka",
            message_id=mid,
            user_id=424242,
        ),
        press_button(
            full_bot, custom_id="counter:baka", message_id=mid, user_id=7
        ),
    )

    assert all(p.exceptions == [] for p in presses)
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
            counter_id,
        )
        == 2
    )
