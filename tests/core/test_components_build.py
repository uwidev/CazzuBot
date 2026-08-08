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


def test_consume_confirm_menu_builds() -> None:
    _assert_builds(utils.ConfirmMenu(author_id=1, delete_after=False))
