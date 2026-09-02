"""Cluster Frog — the spawn behavior: burst child Basic frogs into nearby
text channels; never a catchable cluster frog.
"""

from __future__ import annotations

import asyncio

import pendulum

from cazzubot.models import FrogItemKey
import plugins.frogs.behaviors as behaviors_mod
from plugins.frogs.behaviors import ClusterBurst
from tests.fakes import FakeChannel, InstantAsyncio


async def test_cluster_spawn_bursts_basics_into_zone(
    full_bot,
    monkeypatch,
) -> None:
    """A cluster spawn posts N child Basic frogs, never a cluster frog."""
    bot = full_bot
    # three text channels: id 9 (down), 10 (center), 11 (up)
    gid = bot.config.guild_id
    guild = bot.rest.guilds[gid]
    for cid_, pos in ((9, 1), (10, 2), (11, 3)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        guild.channels[cid_] = channel

    spawned: list[tuple[int, FrogItemKey]] = []

    async def fake_spawn(
        b,
        persist,
        cid: int | None = None,
        species_key: FrogItemKey | None = None,
    ) -> bool:
        spawned.append((cid or 0, species_key or FrogItemKey.BASIC))
        return False

    burst = ClusterBurst()
    burst.spawn_impl = fake_spawn
    monkeypatch.setattr(
        "plugins.frogs.behaviors.random",
        __import__("random").Random(7),
    )
    # the burst sleeps 0.75s between children (Discord rate-limit guard);
    # that timing isn't what this test asserts — stub the module binding,
    # never the global asyncio (the driver harness polls on it)
    monkeypatch.setattr(
        behaviors_mod, "asyncio", InstantAsyncio()
    )

    await burst(
        bot,
        cid=10,
        guild_id=gid,
        persist=30,
        now=pendulum.now("UTC"),
    )
    # children are tracked background tasks — drain the loop
    for _ in range(100):
        if len(spawned) >= 4:
            break
        await asyncio.sleep(0.01)

    assert 4 <= len(spawned) <= 6
    assert {key for _, key in spawned} == {FrogItemKey.BASIC}
    assert {cid_ for cid_, _ in spawned} <= {9, 10, 11}


async def test_cluster_zone_ignores_non_text_and_outside_channels(
    full_bot,
) -> None:
    """Only text channels within the radius count (FROG.md: ±2)."""
    bot = full_bot
    gid = bot.config.guild_id
    guild = bot.rest.guilds[gid]
    for cid_, pos in ((1, 0), (9, 1), (10, 2), (11, 3), (99, 9)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        if cid_ == 99:
            channel.type = None  # not a text channel
        guild.channels[cid_] = channel

    burst = ClusterBurst()
    zone = await burst._zone(bot, gid, 10)  # type: ignore[attr-defined]
    assert [entry[0] for entry in zone] == [1, 9, 10, 11]  # 99 excluded
