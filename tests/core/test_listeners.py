"""cazzubot.listeners — the guild-scoped listener registration helper.

The decorator's drop/pass behavior is exercised through the migrated
plugin listeners (welcome/fun/counter/poll/experience gate tests); these
cover the per-type guild extraction, including the DM edge where
``MessageEvent.guild_id`` would raise.
"""

from __future__ import annotations

from types import SimpleNamespace

from cazzubot.listeners import _event_guild_id
from tests.fakes import FakeMessage


def test_event_guild_id_message_events() -> None:
    """The real ``MessageEvent.guild_id`` asserts non-None — reading it on
    a DM would raise; the helper must use ``message.guild_id`` instead."""
    assert (
        _event_guild_id(SimpleNamespace(message=FakeMessage(guild_id=2)))
        == 2
    )
    assert _event_guild_id(SimpleNamespace(message=FakeMessage())) is None


def test_event_guild_id_interaction_events() -> None:
    assert (
        _event_guild_id(
            SimpleNamespace(interaction=SimpleNamespace(guild_id=2))
        )
        == 2
    )
    assert (
        _event_guild_id(SimpleNamespace(interaction=SimpleNamespace()))
        is None
    )


def test_event_guild_id_falls_back_to_event_attribute() -> None:
    """GuildEvent-style events expose ``guild_id`` directly."""
    assert _event_guild_id(SimpleNamespace(guild_id=2)) == 2
    assert _event_guild_id(SimpleNamespace(guild_id=None)) is None
    assert _event_guild_id(SimpleNamespace()) is None
