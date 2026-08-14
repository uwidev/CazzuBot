"""Frog spawn/catch through the offline driver (manual D4 scenario).

``frog spawn`` blocks on the catch menu like in production; the test
presses the catch button the way a user would and asserts the whole
capture pipeline (DB rows, silent click ack, capture as a standalone
channel message, frog message cleanup) plus the stale-button behavior
after the catch. The spawned frog is a rolled species, so the catch
button's custom_id carries it (``frog:catch:<cid>:<key>``).
"""

from __future__ import annotations

import asyncio

import hikari

from cazzubot.bot import CazzuBot
from tests.driver import press_button, run_slash, wait_for_menu
from tests.fakes import rest_of


def _catch_button(buttons: dict[str, str]) -> str:
    """The spawned frog's catch custom_id (species suffix rolled at spawn)."""
    matches = [
        cid for cid in buttons.values() if cid.startswith("frog:catch:99:")
    ]
    assert matches, f"no catch button for channel 99 in {buttons}"
    return matches[0]


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
    catch_id = _catch_button(buttons)
    species_key = catch_id.rsplit(":", 1)[-1]

    press = await press_button(
        full_bot,
        custom_id=catch_id,
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
    # capture recorded: inventory row for the rolled species + capture
    # counter; the log row stores the species key
    row = await full_bot.db.fetchone(
        """
		SELECT qty FROM inventory
		WHERE uid = 424242 AND item = ?
		""",
        f"frog:{species_key}:normal",
    )
    assert row is not None and row["qty"] == 1
    assert (
        await full_bot.db.fetchval(
            "SELECT capture FROM member_frog WHERE uid = 424242"
        )
        == 1
    )
    assert (
        await full_bot.db.fetchval(
            "SELECT type FROM member_frog_log WHERE uid = 424242"
        )
        == species_key
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
    buttons = await wait_for_menu(full_bot)
    catch_id = _catch_button(buttons)
    first = await press_button(
        full_bot,
        custom_id=catch_id,
        message_id=555,
        user_id=424242,
    )
    await task
    assert (
        first.response_type == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )

    second = await press_button(
        full_bot,
        custom_id=catch_id,
        message_id=555,
        user_id=7,
    )
    # no menu matches any more: no response, no crash
    assert not second.responded
    assert second.exceptions == []
