# pyright: reportArgumentType=false
"""Poll plugin tests — commands, vote modal, persistent vote button.

The commands are invoked directly (owner hooks bypassed); the vote flow
drives ``_handle_vote`` with a fake component interaction and the modal
submission with a fake modal context.
"""

from __future__ import annotations

import pytest

from cazzubot.bot import CazzuBot
from plugins.poll.cog import (
    AutoPopulate,
    Open,
    PollModal,
    Register,
    Send,
    Stats,
    _handle_vote,
)
from plugins.poll.db import (
    add_items_dummy,
    add_poll,
    add_votes,
    get_poll,
    get_results,
)
from plugins.poll.logic import parse_votes, validate_votes
from tests.fakes import (
    FakeComponentInteraction,
    FakeContext,
    FakeMember,
    FakeModalContext,
    first_button_custom_id,
    invoke_command,
)

_UID = 424242


async def _poll_with_items(
    bot: CazzuBot, *, max_vote: int = 2, n_items: int = 3
) -> int:
    pid = await add_poll(bot.db, "title", "desc", max_vote)
    assert pid is not None
    await add_items_dummy(bot.db, pid, n_items)
    return pid


# -- logic: pure parsing -------------------------------------------------


def test_parse_votes() -> None:
    assert parse_votes("1,2") == [1, 2]
    assert parse_votes("1, 2 ,3") == [1, 2, 3]
    assert parse_votes("-1") == [-1]
    with pytest.raises(ValueError):
        parse_votes("")
    with pytest.raises(TypeError):
        parse_votes("1,x")


def test_validate_votes() -> None:
    assert validate_votes([1, 2], upper=3, max_vote=2) == []
    assert validate_votes([9], upper=3, max_vote=2) == [
        "Numbers out of range (1-3): [9]"
    ]
    assert validate_votes([1, 2, 3], upper=3, max_vote=2) == [
        "Too many votes (max 2): got 3"
    ]


# -- modal: submit ----------------------------------------------------------


async def test_modal_submit_records_and_replaces_votes(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot)
    poll = await get_poll(bot.db, pid)
    assert poll is not None
    modal = PollModal(bot, poll, [1, 2, 3])

    mctx = FakeModalContext(values={modal.vote_input: "1,2"}, user=author)
    await modal.on_submit(mctx)
    results = await get_results(bot.db, pid)
    assert [(r.iid, r.count) for r in results] == [(1, 1), (2, 1)]
    assert mctx.sent[-1]["ephemeral"] is True

    # a second submit replaces the user's previous votes
    mctx2 = FakeModalContext(values={modal.vote_input: "3"}, user=author)
    await modal.on_submit(mctx2)
    results = await get_results(bot.db, pid)
    assert [(r.iid, r.count) for r in results] == [(3, 1)]


async def test_modal_submit_rejects_invalid(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot)
    poll = await get_poll(bot.db, pid)
    assert poll is not None
    modal = PollModal(bot, poll, [1, 2, 3])

    mctx = FakeModalContext(values={modal.vote_input: "9"}, user=author)
    await modal.on_submit(mctx)
    assert "❌ Invalid vote" in mctx.sent[-1]["content"]
    assert await get_results(bot.db, pid) == []

    mctx2 = FakeModalContext(values={modal.vote_input: "x"}, user=author)
    await modal.on_submit(mctx2)
    assert "❌ Format error" in mctx2.sent[-1]["content"]


# -- vote button + send ------------------------------------------------------


async def test_poll_vote_opens_modal(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot)
    interaction = FakeComponentInteraction(
        user=author, custom_id=f"poll:vote:{pid}"
    )

    await _handle_vote(bot, interaction, pid)

    assert len(interaction.modals) == 1
    assert interaction.modals[0]["custom_id"] == f"poll:submit:{pid}"
    assert isinstance(interaction.modals[0]["components"], PollModal)


async def test_poll_vote_missing_poll(
    bot: CazzuBot, author: FakeMember
) -> None:
    interaction = FakeComponentInteraction(
        user=author, custom_id="poll:vote:9999"
    )

    await _handle_vote(bot, interaction, 9999)

    assert interaction.responses[-1][0].name == "MESSAGE_CREATE"
    assert (
        interaction.responses[-1][1]["content"]
        == "❌ This poll no longer exists."
    )


async def test_poll_send_records_message_id(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    pid = await _poll_with_items(bot)

    await invoke_command(Send(), ctx, poll_id=pid)

    assert ctx.sent[0].embed is not None
    assert (
        first_button_custom_id(ctx.sent[0].component) == f"poll:vote:{pid}"
    )
    poll = await get_poll(bot.db, pid)
    assert poll is not None and poll.mid == 1  # FakeContext response id

    # missing poll -> error
    await invoke_command(Send(), ctx, poll_id=9999)
    assert "does not exist" in (ctx.sent[-1].content or "")


# -- register / open / stats / populate ------------------------------------


async def test_poll_register_creates_poll(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await invoke_command(
        Register(), ctx, title="title", desc="desc", max_vote=2
    )
    assert "ID#" in (ctx.sent[-1].content or "")
    pid_row = await bot.db.fetchone("SELECT id FROM poll")
    assert pid_row is not None
    poll = await get_poll(bot.db, pid_row["id"])
    assert poll is not None and poll.max_vote == 2


async def test_poll_open_toggles(bot: CazzuBot, ctx: FakeContext) -> None:
    pid = await _poll_with_items(bot)

    await invoke_command(Open(), ctx, poll_id=pid, open=False)

    poll = await get_poll(bot.db, pid)
    assert poll is not None and poll.open == 0
    assert "closed" in (ctx.sent[-1].content or "")


async def test_poll_stats_formats_results(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    pid = await _poll_with_items(bot)
    await add_votes(bot.db, pid, [1, 1, 2], _UID)

    await invoke_command(Stats(), ctx, poll_id=pid)

    content = ctx.sent[-1].content
    assert content is not None
    assert "```Item       Count   Percent\n" in content
    # votes: item 1 twice, item 2 once (3 total)
    assert "1              2    66.67%" in content
    assert "2              1    33.33%" in content

    await invoke_command(Stats(), ctx, poll_id=9999)
    assert "No votes have been cast yet." in (ctx.sent[-1].content or "")


async def test_auto_populate_bounds(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    pid = await _poll_with_items(bot, n_items=0)

    await invoke_command(AutoPopulate(), ctx, pid=pid, n=2)
    assert "👍 Items have been added." in (ctx.sent[-1].content or "")

    await invoke_command(AutoPopulate(), ctx, pid=pid, n=0)
    assert "n must be between 1 and 50." in (ctx.sent[-1].content or "")
