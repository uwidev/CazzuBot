"""The slash-command pipeline through the offline driver.

These tests exercise what direct ``invoke``-based unit tests cannot: option
solving (including defaults and channel resolution), the CHECKS step
(debug gate, admin/owner hooks), UserInputError translation into ephemeral
replies, the window reporting flow, and menu-backed commands like
``experience leaderboard``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import hikari
import pendulum

from cazzubot.bot import CazzuBot
from tests.conftest import boot_full_bot
from tests.driver import press_button, run_slash, wait_for_menu


async def test_debug_gate_blocks_non_owner(tmp_path: Path) -> None:
    """Manual B2: in -d mode only the owner/debug users run commands."""
    bot = await boot_full_bot(tmp_path, debug=True)
    try:
        blocked = await run_slash(bot, "experience quiet list", user_id=424242)
        assert not blocked.responded
        assert blocked.exceptions == []

        allowed = await run_slash(
            bot, "experience quiet list", user_id=1, username="owner"
        )
        assert allowed.response_type == hikari.ResponseType.MESSAGE_CREATE
        assert allowed.exceptions == []
    finally:
        await bot._on_stopping(  # pyright: ignore[reportPrivateUsage]
            hikari.StoppingEvent(app=bot)
        )


async def test_user_input_error_becomes_ephemeral_reply(
    full_bot: CazzuBot,
) -> None:
    """Manual L1: service validation errors surface as ✖-free ephemerals."""
    result = await run_slash(
        full_bot,
        "frog register",
        options={"interval": "garbage"},
        user_id=424242,
    )

    assert result.exceptions == []
    assert result.response_type == hikari.ResponseType.MESSAGE_CREATE
    assert result.first_response is not None
    assert (
        result.first_response.get("flags", 0)
        & hikari.MessageFlag.EPHEMERAL
    )
    assert "not a valid time" in str(
        result.first_response.get("content", "")
    )


async def test_frog_register_window_and_spawn_task(
    full_bot: CazzuBot,
) -> None:
    """A successful admin command reports through the ✓ window and queues
    the spawn task (defaults for persist/fuzzy exercised)."""
    from plugins.frogs import db as frog_db

    await frog_db.set_enabled(full_bot.settings, True)
    result = await run_slash(
        full_bot,
        "frog register",
        options={"interval": "10m"},
        user_id=424242,
    )

    assert result.exceptions == []
    assert result.response_type == hikari.ResponseType.MESSAGE_CREATE
    assert result.first_response is not None
    content = str(result.first_response.get("content", ""))
    assert content.startswith("✓")
    assert "Spawn channel registered" in content
    tasks = await full_bot.scheduler.get("frog")
    assert len(tasks) == 1
    assert tasks[0].payload["cid"] == 99


async def test_exp_top_paging(full_bot: CazzuBot) -> None:
    """Manual C3: the leaderboard pager edits the page in place.

    12 rows = the tail case: page 2 must be reachable (the old floor
    division ``len(rows) // 10`` capped the pager at page 1 and stranded
    rows 10-11)."""
    now = pendulum.now("UTC")
    for uid in range(101, 113):
        await full_bot.db.execute(
            "INSERT INTO member_exp_log (uid, exp, at, source) VALUES (?, 10, ?, 'message')",
            uid,
            now.to_iso8601_string(),
        )

    task = asyncio.create_task(
        run_slash(full_bot, "experience leaderboard", user_id=424242, timeout=10.0)
    )
    buttons = await wait_for_menu(full_bot)

    page = await press_button(
        full_bot,
        custom_id=buttons["▶"],
        message_id=555,
        user_id=424242,
    )
    # the pager stays interactive for its 30s attach window by design —
    # the press assertions are what matter, the command ends on timeout
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert page.exceptions == []
    # respond(edit=True) is the atomic ack+edit — no "thinking" bubble
    assert page.response_type == hikari.ResponseType.MESSAGE_UPDATE
    assert page.first_response is not None
    embed = page.first_response.get("embed")
    assert embed is not None and "Page: **`2`**" in embed.description


async def test_exp_top_wrong_user_denied(full_bot: CazzuBot) -> None:
    task = asyncio.create_task(
        run_slash(full_bot, "experience leaderboard", user_id=424242, timeout=10.0)
    )
    buttons = await wait_for_menu(full_bot)
    try:
        press = await press_button(
            full_bot,
            custom_id=buttons["▶"],
            message_id=555,
            user_id=7,
        )
        assert press.exceptions == []
        assert press.response_type == hikari.ResponseType.MESSAGE_CREATE
        assert press.first_response is not None
        assert (
            press.first_response.get("flags", 0)
            & hikari.MessageFlag.EPHEMERAL
        )
        assert "not yours to page" in str(
            press.first_response.get("content", "")
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
