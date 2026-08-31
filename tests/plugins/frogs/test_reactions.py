"""Frog reactions — the message-time listener for FrogSeam.FROG_REACTION.

A user with an active reaction contribution (Pog/Froggers consumed) has a
per-message chance the bot reacts with the froggers emoji; the fold reads
each contribution's source back to its status class and picks by priority
(expiry of the winner falls back to the next live sibling). The cooldown
and the unpublished-emoji no-op are listener behavior.

The frog modules are resolved at call time (``tests/plugins/frogs/_current.py``):
the plugin-reload tests purge and re-import ``plugins.frogs.*`` mid-suite,
so collection-time references would go stale against the registry.
"""
# driving the typed guild-scoped listener with a fake event (same as the
# experience listener's tests)
# pyright: reportArgumentType=false

from __future__ import annotations

import pendulum
import pytest

from cazzubot.assets import asset_key
from cazzubot.statuses import Scope, StatusContribution, ScopeKind
from plugins.frogs.assets import FrogAsset
from plugins.frogs.seams import FrogSeam

from tests.plugins.frogs._current import reactions, statuses

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
    rx = reactions()
    monkeypatch.setattr(rx.random, "random", fixed.random)
    rx._last_react.clear()
    monkeypatch.setattr(rx, "_last_react", {})
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


async def _seed_reaction(bot, uid: int) -> None:
    """Grant the Pog reaction status (1% — the fold reads it off the class)."""
    await statuses().POG_REACTION.apply(
        bot, scope=Scope.member(uid), provenance="frog:pog:normal"
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
    await reactions().on_message(event)


async def test_message_with_reaction_contribution_reacts(
    full_bot,
    seeded_roll,
) -> None:
    bot = full_bot
    await _publish_froggers_emoji(bot)
    await _seed_reaction(bot, 123)
    before = len(bot.rest.reactions)
    await _dispatch_message(bot, uid=123)
    assert len(bot.rest.reactions) == before + 1
    channel_id, message_id, emoji = bot.rest.reactions[-1]
    assert emoji == _EMOJI


async def test_cooldown_blocks_second_react(full_bot, seeded_roll) -> None:
    bot = full_bot
    await _publish_froggers_emoji(bot)
    await _seed_reaction(bot, 123)
    await _dispatch_message(bot, uid=123)
    n_after_first = len(bot.rest.reactions)
    await _dispatch_message(bot, uid=123)  # within 10s
    assert len(bot.rest.reactions) == n_after_first


async def test_no_contribution_never_reacts(full_bot, seeded_roll) -> None:
    bot = full_bot
    await _dispatch_message(bot, uid=999)
    assert bot.rest.reactions == []


def _contrib(source: str) -> StatusContribution:
    """One in-memory reaction contribution row (no DB needed)."""
    return StatusContribution(
        scope_kind=ScopeKind.MEMBER,
        scope_id=1,
        seam=FrogSeam.FROG_REACTION.key,
        source=source,
        payload={},
        expires_at=None,
    )


def test_fold_picks_highest_priority() -> None:
    """The fold maps source→class and picks by (priority, source key)."""
    rx, st = reactions(), statuses()
    # both live: Froggers (priority 2) wins over Pog (priority 1)
    both = [
        _contrib("frog:blessing:pog"),
        _contrib("frog:blessing:froggers"),
    ]
    assert rx._best_reaction(both) is st.FROGGERS_REACTION
    # only Pog live: Pog wins
    assert (
        rx._best_reaction([_contrib("frog:blessing:pog")])
        is st.POG_REACTION
    )
    # unknown sources (a retired status) are skipped; no known → None
    assert rx._best_reaction([_contrib("frog_reaction")]) is None
    assert rx._best_reaction([]) is None


async def test_fold_falls_back_to_pog_after_froggers_expiry(
    full_bot,
) -> None:
    """Expiry of the winner reveals the next live sibling — no merge logic."""
    bot = full_bot
    rx, st = reactions(), statuses()
    now = pendulum.now("UTC")
    await st.FROGGERS_REACTION.apply(
        bot,
        scope=Scope.member(1),
        provenance="frog:froggers:normal",
        now=now,
    )
    await st.POG_REACTION.apply(
        bot,
        scope=Scope.member(1),
        provenance="frog:pog:normal",
        now=now.add(minutes=10),
    )
    # T+1h+ε: Froggers (expires T+1h) is pruned; Pog (expires T+1h10m) lives
    contribs = await bot.statuses.list(
        Scope.member(1),
        FrogSeam.FROG_REACTION,
        now=now.add(hours=1, minutes=1),
    )
    assert {c.source for c in contribs} == {"frog:blessing:pog"}
    assert rx._best_reaction(contribs) is st.POG_REACTION
