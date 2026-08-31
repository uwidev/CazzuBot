"""Frog reactions — the message-time listener for FrogSeam.FROG_REACTION.

A user with an active reaction contribution (Pog/Froggers consumed) has a
per-message chance the bot reacts with the froggers emoji; the cooldown
and the unpublished-emoji no-op are listener behavior.
"""
# driving the typed guild-scoped listener with a fake event (same as the
# experience listener's tests)
# pyright: reportArgumentType=false

from __future__ import annotations

import pytest

from cazzubot.assets import asset_key
from cazzubot.statuses import Scope
from plugins.frogs import reactions
from plugins.frogs.assets import FrogAsset
from plugins.frogs.seams import FrogSeam, FrogStatus

_EMOJI = "<:frog_froggers:9001>"
_ASSET_KEY = asset_key(FrogAsset.FROG_FROGGERS)


@pytest.fixture
def seeded_roll(monkeypatch):
    """Force `random.random()` to 0.0 (always roll) / 1.0 (never)."""
    store: dict[str, float] = {}

    class _Fixed:
        def random(self) -> float:
            return store.get("v", 0.0)

        def set(self, v: float) -> None:
            store["v"] = v

    fixed = _Fixed()  # type: ignore[attr-defined]
    monkeypatch.setattr(reactions.random, "random", fixed.random)
    reactions._last_react.clear()
    monkeypatch.setattr(reactions, "_last_react", {})
    return fixed


async def _publish_froggers_emoji(bot) -> None:
    """Publish the froggers emoji asset row (assets.get reads its url)."""
    await bot.db.execute(
        "INSERT OR REPLACE INTO asset (key, kind, sha256, path, url) "
        "VALUES (?, 'emoji', 'x', ?, ?)",
        _ASSET_KEY,
        "assets/frog-froggers.png",
        _EMOJI,
    )


async def _seed_reaction(bot, uid: int, chance: float) -> None:
    await bot.statuses.publish(
        Scope.member(uid),
        FrogSeam.FROG_REACTION,
        source=FrogStatus.REACTION.key,
        payload={"chance": chance},
        duration=None,
        now=None,
    )


async def _dispatch_message(bot, uid: int) -> None:
    """Deliver a guild-style message event straight to the listener.

    The listener reads ``event.message`` fields (like the experience
    listener) plus ``event.app``; ``FakeMessageCreateEvent`` (the fakes'
    hikari stand-in) around a ``FakeMessage`` drives it without the
    gateway.
    """
    from tests.fakes import FakeMember, FakeMessage, FakeMessageCreateEvent

    author = FakeMember(id=uid, name="tester")
    message = FakeMessage(
        id=222, channel_id=111, author=author, guild_id=bot.config.guild_id
    )
    event = FakeMessageCreateEvent(message=message, app=bot)
    await reactions.on_message(event)


async def test_message_with_reaction_contribution_reacts(
    full_bot,
    seeded_roll,
) -> None:
    bot = full_bot
    await _publish_froggers_emoji(bot)
    await _seed_reaction(bot, 123, 1.0)
    before = len(bot.rest.reactions)
    await _dispatch_message(bot, uid=123)
    assert len(bot.rest.reactions) == before + 1
    channel_id, message_id, emoji = bot.rest.reactions[-1]
    assert emoji == _EMOJI


async def test_cooldown_blocks_second_react(full_bot, seeded_roll) -> None:
    bot = full_bot
    await _publish_froggers_emoji(bot)
    await _seed_reaction(bot, 123, 1.0)
    await _dispatch_message(bot, uid=123)
    n_after_first = len(bot.rest.reactions)
    await _dispatch_message(bot, uid=123)  # within 10s
    assert len(bot.rest.reactions) == n_after_first


async def test_no_contribution_never_reacts(full_bot, seeded_roll) -> None:
    bot = full_bot
    await _dispatch_message(bot, uid=999)
    assert bot.rest.reactions == []
