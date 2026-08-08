"""Every shipped menu/modal must serialize to a component payload.

hikari's respond/create_modal_response expect either a single builder
(``component=``, which needs a public ``build()``) or a *sequence* of
builders (``components=``). lightbulb's Menu/Modal containers implement
the sequence protocol over a private ``_build()`` and have no public
``build()`` — so they must always be passed as ``components=``. This test
pins the actual serialization path so a wrong kwarg can't sneak back in
(regression: 'frog spawn' crashed with "'FrogCatchMenu' object has no
attribute 'build'").
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pendulum

from cazzubot import utils
from plugins.experience.cog import TopMenu
from plugins.frogs import factory
from plugins.poll.cog import PollModal
from tests.fakes import FakeChannel, FakeContext, FakeGuild, FakeMember

_GUILD = FakeGuild(id=2)
_MEMBER = FakeMember(id=1, name="cirno", guild=_GUILD)
_CHANNEL = FakeChannel(id=99, guild_id=2)


def _assert_builds(container: Any) -> None:
    """The container's rows must serialize to a component payload."""
    rows = container._build()
    assert rows, "menu/modal must contain at least one row"
    for row in rows:
        payload, _attachments = row.build()
        assert "components" in payload


def test_confirm_menu_builds() -> None:
    _assert_builds(utils.ConfirmMenu(author_id=1))


def test_top_menu_builds() -> None:
    ctx = FakeContext(
        bot=object(), member=_MEMBER, guild=_GUILD, channel=_CHANNEL
    )
    menu = TopMenu(
        cast(Any, object()),
        cast(Any, ctx),
        pendulum.datetime(2026, 1, 1),
        [(1, 1, 100)],
    )
    _assert_builds(menu)


def test_frog_catch_menu_builds() -> None:
    _assert_builds(factory.FrogCatchMenu(bot=cast(Any, object())))


def test_poll_modal_builds() -> None:
    poll = SimpleNamespace(id=1, max_vote=2, title="t", description="")
    modal = PollModal(cast(Any, object()), cast(Any, poll), [1, 2, 3])
    _assert_builds(modal)


def test_poll_modal_shows_rules_display() -> None:
    """The modal carries a text-display row with the vote range + max votes."""
    poll = SimpleNamespace(id=1, max_vote=2, title="t", description="")
    modal = PollModal(cast(Any, object()), cast(Any, poll), [1, 2, 3])
    rows = modal._build()
    displays = [
        row.build()[0]["components"][0]
        for row in rows
        if row.build()[0]["components"]
        and row.build()[0]["components"][0]["type"].name == "TEXT_DISPLAY"
    ]
    assert displays, "modal must contain a text-display row"
    content = displays[0]["content"]
    assert "Max votes: 2" in content
    assert "Range: 1 to 3" in content
    assert "comma-separated" in content


def test_consume_confirm_menu_builds() -> None:
    _assert_builds(utils.ConfirmMenu(author_id=1, delete_after=False))


def test_frog_catch_button_emoji_is_id() -> None:
    """Custom-emoji tags must serialize to {'id': ...}, not a raw name."""
    menu = factory.FrogCatchMenu(bot=cast(Any, object()))
    row_payload, _attachments = menu._build()[0].build()
    button = row_payload["components"][0]
    assert button["emoji"] == {"id": "752290769712316506"}
    assert "name" not in button["emoji"]


def test_button_emoji_helper() -> None:
    assert (
        utils.button_emoji("<:cirnoNet:752290769712316506>")
        == 752290769712316506
    )
    assert (
        utils.button_emoji("<a:animated:123456789012345678>")
        == 123456789012345678
    )
    assert utils.button_emoji("👍") == "👍"
    assert utils.button_emoji("no tag") == "no tag"
