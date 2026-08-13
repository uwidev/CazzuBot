"""Frog spawn/catch through the offline driver (manual D4 scenario).

``frog spawn`` blocks on the catch menu like in production; the test
presses the catch button the way a user would and asserts the whole
capture pipeline (DB rows, silent click ack, capture as a standalone
channel message, frog message cleanup) plus the stale-button behavior
after the catch.
"""

from __future__ import annotations

import asyncio

import hikari

from cazzubot.bot import CazzuBot
from tests.driver import press_button, run_slash, wait_for_menu
from tests.fakes import rest_of


async def test_frog_spawn_then_catch(full_bot: CazzuBot) -> None:
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "frog spawn",
            user_id=1,
            username="owner",
            # the command blocks on the catch menu (30s attach window)
            timeout=40.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    assert "frog:catch:99" in buttons.values()

    press = await press_button(
        full_bot,
        custom_id="frog:catch:99",
        message_id=555,
        user_id=424242,
    )
    spawn = await task

    assert press.exceptions == []
    assert spawn.exceptions == []
    # the click is acked silently — DEFERRED_MESSAGE_UPDATE (no response
    # message, no "thinking" bubble); the capture is a standalone channel
    # message, not an interaction response (no reply styling)
    assert (
        press.response_type == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    assert press.response_message_id is None
    assert spawn.followups == []
    # exactly one standalone channel message: the frog itself was spawned
    # via the slash interaction response (webhook-minted, not in `created`)
    created = rest_of(full_bot).created
    assert len(created) == 1
    assert created[0].channel_id == 99
    # capture recorded: log row + inventory + capture counter
    row = await full_bot.db.fetchone(
        "SELECT normal, capture FROM member_frog WHERE uid = 424242"
    )
    assert row is not None and row["normal"] == 1 and row["capture"] == 1
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM member_frog_log WHERE uid = 424242"
        )
        == 1
    )
    # the frog message is deleted after the catch
    frog_mid = spawn.response_message_id
    assert frog_mid is not None
    assert (99, frog_mid) in rest_of(full_bot).deleted


async def test_catch_button_is_stale_after_capture(
    full_bot: CazzuBot,
) -> None:
    """A second press on the caught frog is silently ignored (menu gone)."""
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "frog spawn",
            user_id=1,
            username="owner",
            timeout=40.0,
        )
    )
    await wait_for_menu(full_bot)
    first = await press_button(
        full_bot,
        custom_id="frog:catch:99",
        message_id=555,
        user_id=424242,
    )
    await task
    assert (
        first.response_type == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )

    second = await press_button(
        full_bot,
        custom_id="frog:catch:99",
        message_id=555,
        user_id=7,
    )
    # no menu matches any more: no response, no crash
    assert not second.responded
    assert second.exceptions == []
