"""Poll plugin through the offline driver (manual F2/F3 scenarios).

Full vote flow: register → auto-populate → send (vote button) → press the
button (modal opens) → submit the modal (vote recorded). Everything runs
through hikari's deserializer + lightbulb's modal machinery.
"""

from __future__ import annotations


import hikari

from cazzubot.bot import CazzuBot
from tests.driver import (
    modal_input_custom_id,
    press_button,
    run_slash,
    submit_modal,
    wait_for_modal,
)


async def _register_poll_with_items(
    full_bot: CazzuBot,
) -> tuple[int, int]:
    """Register a poll (max 1 vote) with 3 items; return (pid, mid)."""
    registered = await run_slash(
        full_bot,
        "poll register",
        options={"title": "Best frog", "desc": "Vote now"},
        user_id=1,
        username="owner",
    )
    assert registered.response_type == hikari.ResponseType.MESSAGE_CREATE
    pid = await full_bot.db.fetchval(
        "SELECT id FROM poll ORDER BY id DESC LIMIT 1"
    )
    assert pid is not None

    await run_slash(
        full_bot,
        "poll item auto_populate",
        options={"pid": pid, "n": 3},
        user_id=1,
        username="owner",
    )

    sent = await run_slash(
        full_bot,
        "poll send",
        options={"poll_id": pid},
        user_id=1,
        username="owner",
    )
    assert sent.response_type == hikari.ResponseType.MESSAGE_CREATE
    mid = sent.response_message_id
    assert mid is not None
    return pid, mid


async def test_poll_vote_modal_flow(full_bot: CazzuBot) -> None:
    pid, mid = await _register_poll_with_items(full_bot)

    opened = await run_slash(
        full_bot,
        "poll open",
        options={"poll_id": pid, "open": True},
        user_id=1,
        username="owner",
    )
    assert opened.exceptions == []

    vote = await press_button(
        full_bot,
        custom_id=f"poll:vote:{pid}",
        message_id=mid,
        user_id=424242,
    )
    assert vote.exceptions == []
    assert vote.modals, "vote press should open a modal"
    assert vote.modals[0]["custom_id"] == f"poll:submit:{pid}"
    assert vote.modals[0]["title"] == "Vote on the poll"

    await wait_for_modal(full_bot, f"poll:submit:{pid}")
    input_cid = modal_input_custom_id(vote.modals[0]["components"])

    submitted = await submit_modal(
        full_bot,
        custom_id=f"poll:submit:{pid}",
        values={input_cid: "1"},
        user_id=424242,
    )

    assert submitted.exceptions == []
    assert submitted.response_type == hikari.ResponseType.MESSAGE_CREATE
    assert submitted.first_response is not None
    assert (
        submitted.first_response.get("flags", 0)
        & hikari.MessageFlag.EPHEMERAL
    )
    rows = await full_bot.db.fetchall(
        "SELECT iid, count FROM poll_vote WHERE pid = ? AND uid = 424242",
        pid,
    )
    assert [(r["iid"], r["count"]) for r in rows] == [(1, 1)]


async def test_poll_vote_rejects_invalid_items(full_bot: CazzuBot) -> None:
    pid, mid = await _register_poll_with_items(full_bot)
    await run_slash(
        full_bot,
        "poll open",
        options={"poll_id": pid, "open": True},
        user_id=1,
        username="owner",
    )
    vote = await press_button(
        full_bot,
        custom_id=f"poll:vote:{pid}",
        message_id=mid,
        user_id=424242,
    )
    await wait_for_modal(full_bot, f"poll:submit:{pid}")
    input_cid = modal_input_custom_id(vote.modals[0]["components"])

    submitted = await submit_modal(
        full_bot,
        custom_id=f"poll:submit:{pid}",
        values={input_cid: "99"},
        user_id=424242,
    )

    assert submitted.exceptions == []
    assert submitted.first_response is not None
    assert "Invalid vote" in str(
        submitted.first_response.get("content", "")
    )
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM poll_vote WHERE pid = ?", pid
        )
        == 0
    )


async def test_poll_vote_button_on_unknown_poll(
    full_bot: CazzuBot,
) -> None:
    press = await press_button(
        full_bot,
        custom_id="poll:vote:9999",
        message_id=555,
        user_id=424242,
    )
    assert press.exceptions == []
    assert press.response_type == hikari.ResponseType.MESSAGE_CREATE
    assert press.first_response is not None
    assert "no longer exists" in str(
        press.first_response.get("content", "")
    )
