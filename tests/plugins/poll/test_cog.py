"""Poll cog tests — app commands, vote modal, persistent view re-registration.

App-command methods take an ``Interaction``; ``cog_check`` (owner-only) is
bypassed by direct invocation. The vote button's persistence regression:
``PollPlugin.on_load`` must re-attach views for stored ``mid``s.
"""

from __future__ import annotations

import pytest

from cazzubot.bot import CazzuBot
from tests.fakes import first_button_custom_id
from plugins.poll import (
    PollPlugin,
    PollView,
    add_items_dummy,
    add_poll,
    add_votes,
    get_poll,
    get_results,
    set_mid,
)
from plugins.poll import PollCog, PollModal
from tests.fakes import FakeInteraction, FakeMember

_UID = 424242


def _cog(bot: CazzuBot) -> PollCog:
    cog = bot.get_cog(PollCog.__cog_name__)
    assert isinstance(cog, PollCog)
    return cog


async def _invoke(bot: CazzuBot, command: str, *args: object) -> None:
    """Invoke an app-command callback directly (app commands aren't callable).

    ``app_commands.Command`` objects have no ``__call__``; their raw callback
    is ``Command.callback`` (bound ``self`` is the cog).
    """
    cmd = getattr(_cog(bot), command)
    callback = getattr(cmd, "callback")
    assert callback is not None
    await callback(_cog(bot), *args)


def _interaction(_bot: CazzuBot, author: FakeMember) -> FakeInteraction:
    return FakeInteraction(id=1, user=author)


async def _poll_with_items(
    bot: CazzuBot, *, max_vote: int = 2, n_items: int = 3
) -> int:
    pid = await add_poll(bot.db, "title", "desc", max_vote)
    assert pid is not None
    await add_items_dummy(bot.db, pid, n_items)
    return pid


# -- modal: pure parsing ----------------------------------------------------


def test_parse_votes() -> None:
    modal = PollModal.__new__(PollModal)  # type: ignore[call-arg]
    assert modal.parse_votes("1,2") == [1, 2]
    assert modal.parse_votes("1, 2 ,3") == [1, 2, 3]
    assert modal.parse_votes("-1") == [-1]
    with pytest.raises(ValueError):
        modal.parse_votes("")
    with pytest.raises(TypeError):
        modal.parse_votes("1,x")


def test_validate_votes() -> None:
    modal = PollModal.__new__(PollModal)  # type: ignore[call-arg]
    modal.upper, modal.max_vote = 3, 2
    assert modal.validate_votes([1, 2]) == []
    assert modal.validate_votes([9]) == ["Numbers out of range (1-3): [9]"]
    assert modal.validate_votes([1, 2, 3]) == [
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
    interaction = _interaction(bot, author)
    modal.vote_input._value = "1,2"  # pyright: ignore[reportPrivateUsage]
    await modal.on_submit(interaction)
    results = await get_results(bot.db, pid)
    assert [(r.iid, r.count) for r in results] == [(1, 1), (2, 1)]
    assert interaction.response.calls[-1][0] == "send_message"

    # a second submit replaces the user's previous votes
    modal.vote_input._value = "3"  # pyright: ignore[reportPrivateUsage]
    await modal.on_submit(interaction)
    results = await get_results(bot.db, pid)
    assert [(r.iid, r.count) for r in results] == [(3, 1)]


async def test_modal_submit_rejects_invalid(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot)
    poll = await get_poll(bot.db, pid)
    assert poll is not None
    modal = PollModal(bot, poll, [1, 2, 3])
    interaction = _interaction(bot, author)

    modal.vote_input._value = "9"  # pyright: ignore[reportPrivateUsage]
    await modal.on_submit(interaction)
    assert (
        "❌ Invalid vote" in interaction.response.calls[-1][1]["content"]
    )
    assert await get_results(bot.db, pid) == []

    modal.vote_input._value = "x"  # pyright: ignore[reportPrivateUsage]
    await modal.on_submit(interaction)
    assert (
        "❌ Format error" in interaction.response.calls[-1][1]["content"]
    )


# -- view + send ------------------------------------------------------------


async def test_poll_view_opens_vote_modal(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot)
    view = PollView(bot, pid)
    interaction = _interaction(bot, author)
    button = view.children[0]
    assert button.callback is not None

    await button.callback(interaction)

    call = interaction.response.calls[-1]
    assert call[0] == "send_modal"
    assert isinstance(call[1]["modal"], PollModal)


async def test_poll_view_missing_poll(
    bot: CazzuBot, author: FakeMember
) -> None:
    view = PollView(bot, 9999)
    interaction = _interaction(bot, author)
    button = view.children[0]
    assert button.callback is not None

    await button.callback(interaction)

    assert interaction.response.calls[-1] == (
        "send_message",
        {"content": "❌ This poll no longer exists.", "ephemeral": True},
    )


async def test_poll_send_records_message_id(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot)
    interaction = _interaction(bot, author)

    await _invoke(bot, "poll_send", interaction, pid)

    sent = interaction.response.calls[-1]
    assert sent[0] == "send_message"
    assert isinstance(sent[1]["embed"], object)
    assert sent[1]["view"] is not None
    poll = await get_poll(bot.db, pid)
    assert poll is not None and poll.mid == 555

    # missing poll -> error
    await _invoke(bot, "poll_send", interaction, 9999)
    assert "does not exist" in interaction.response.calls[-1][1]["content"]


# -- register / open / stats / populate ------------------------------------


async def test_poll_register_creates_poll(
    bot: CazzuBot, author: FakeMember
) -> None:
    interaction = _interaction(bot, author)
    await _invoke(bot, "poll_register", interaction, "title", "desc", 2)
    assert "ID#" in interaction.response.calls[-1][1]["content"]
    pid_row = await bot.db.fetchone("SELECT id FROM poll")
    assert pid_row is not None
    pid = pid_row["id"]
    poll = await get_poll(bot.db, pid)
    assert poll is not None and poll.max_vote == 2


async def test_poll_open_toggles(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot)
    interaction = _interaction(bot, author)

    await _invoke(bot, "poll_open", interaction, pid, False)
    poll = await get_poll(bot.db, pid)
    assert poll is not None and poll.open == 0
    assert "closed" in interaction.response.calls[-1][1]["content"]


async def test_poll_stats_formats_results(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot)
    await add_votes(bot.db, pid, [1, 1, 2], _UID)
    interaction = _interaction(bot, author)

    await _invoke(bot, "poll_stats", interaction, pid)

    content = interaction.response.calls[-1][1]["content"]
    assert "1" in content and "2" in content

    await _invoke(bot, "poll_stats", interaction, 9999)
    assert (
        "No votes have been cast yet."
        in interaction.response.calls[-1][1]["content"]
    )


async def test_auto_populate_bounds(
    bot: CazzuBot, author: FakeMember
) -> None:
    pid = await _poll_with_items(bot, n_items=0)
    interaction = _interaction(bot, author)

    await _invoke(bot, "poll_item_auto_populate", interaction, pid, 2)
    assert (
        "👍 Items have been added."
        in interaction.response.calls[-1][1]["content"]
    )

    await _invoke(bot, "poll_item_auto_populate", interaction, pid, 0)
    assert (
        "n must be between 1 and 50."
        in interaction.response.calls[-1][1]["content"]
    )


# -- regression: persistent view re-attachment on boot ------------------


async def test_on_load_reattaches_poll_views(
    bot: CazzuBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await add_poll(bot.db, "t", "d", 1)
    assert pid is not None
    await set_mid(bot.db, pid, 12345)
    calls: list[tuple[int, int]] = []

    def spy(view: PollView, *, message_id: int) -> None:
        calls.append((view.poll_id, message_id))

    monkeypatch.setattr(bot, "add_view", spy)

    await PollPlugin().on_load(bot)

    assert calls == [(pid, 12345)]
    # the button that gets baked into messages carries the stable id
    assert (
        calls and first_button_custom_id(PollView(bot, pid)) == "poll:vote"
    )
