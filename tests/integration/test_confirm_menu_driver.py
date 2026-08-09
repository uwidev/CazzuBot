"""Confirm-menu flows through the offline driver.

Regression-proofs the manual-test failures (MANUAL_TEST.md C4/D3): the
confirm prompt must ack the click, resolve the prompt via
``INITIAL_RESPONSE_IDENTIFIER`` (not the interaction id), and let the
command resume with the user's answer — all within the 3s budget, with no
handler exceptions.
"""

from __future__ import annotations

import asyncio

import hikari
import pytest

from cazzubot.bot import CazzuBot
from tests.driver import press_button, run_slash, wait_for_menu


async def test_author_confirm_yes_resumes_command(
    full_bot: CazzuBot,
) -> None:
    """``exp resync`` waits on the menu; a Yes press unblocks it."""
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "exp resync",
            user_id=1,
            username="owner",
            # the command blocks on the confirm menu (7s attach window);
            # the 3s budget only binds the press's initial response
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)

    press = await press_button(
        full_bot,
        custom_id=buttons["Yes"],
        message_id=555,
        user_id=1,
        username="owner",
    )

    result = await task
    assert press.exceptions == []
    assert result.exceptions == []
    # the click is acked (deferred update) and the prompt deleted
    assert (
        press.response_type == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    assert "@original" in press.deletes
    # the window flushed its info line, then the ✓ success line
    contents = [f.get("content", "") for f in result.followups]
    assert any("Fetching exp logs..." in c for c in contents)
    assert any("✓ Lifetime exp synced." in c for c in contents)


async def test_author_confirm_wrong_user_rejected(
    full_bot: CazzuBot,
) -> None:
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "exp resync",
            user_id=1,
            username="owner",
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    try:
        press = await press_button(
            full_bot,
            custom_id=buttons["Yes"],
            message_id=555,
            user_id=424242,
        )
        # the outsider gets an ephemeral refusal; the menu stays alive
        assert press.response_type == hikari.ResponseType.MESSAGE_CREATE
        assert press.first_response is not None
        assert (
            press.first_response.get("flags", 0)
            & hikari.MessageFlag.EPHEMERAL
        )
        assert "not for you" in str(
            press.first_response.get("content", "")
        )
        assert press.exceptions == []
        # the command is still waiting for the author's click
        assert not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    ("button_label", "expected_normal", "expected_exp_logs"),
    [
        pytest.param("Yes", 4, 1, id="yes-awards-exp"),
        pytest.param("No", 5, 0, id="no-changes-nothing"),
    ],
)
async def test_frog_consume_confirm(
    full_bot: CazzuBot,
    button_label: str,
    expected_normal: int,
    expected_exp_logs: int,
) -> None:
    await full_bot.db.execute(
        "INSERT OR IGNORE INTO member_frog (uid, normal, frozen, capture) VALUES (424242, 5, 0, 5)"
    )
    task = asyncio.create_task(
        run_slash(full_bot, "frog consume", user_id=424242, timeout=10.0)
    )
    buttons = await wait_for_menu(full_bot)

    press = await press_button(
        full_bot,
        custom_id=buttons[button_label],
        message_id=555,
        user_id=424242,
    )
    result = await task

    assert press.exceptions == []
    assert result.exceptions == []
    row = await full_bot.db.fetchone(
        "SELECT normal FROM member_frog WHERE uid = 424242"
    )
    assert row is not None and row["normal"] == expected_normal
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM member_exp_log WHERE uid = 424242"
        )
        == expected_exp_logs
    )
    if button_label == "Yes":
        # delete_after=False: the prompt keeps its message but loses its buttons
        assert any(
            payload.get("component") is None
            for _mid, payload in press.edits
        )
        # the post-consume summary edits the prompt message
        assert any("embed" in payload for _mid, payload in result.edits)
