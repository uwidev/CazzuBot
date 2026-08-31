"""Cluster Frog — the spawn hook: burst child Basic frogs into nearby text
channels; never a catchable cluster frog.
"""

from __future__ import annotations

import asyncio

import pendulum

from cazzubot.models import FrogItemKey
from plugins.frogs.outcomes import ClusterOutcome, ClusterPayload
from tests.fakes import FakeChannel


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

    outcome = ClusterOutcome()
    outcome.spawn_impl = fake_spawn
    monkeypatch.setattr(
        "plugins.frogs.outcomes.random",
        __import__("random").Random(7),
    )

    await outcome.spawn(
        bot,
        ClusterPayload(),
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

    assert 4 <= len(spawned) <= 10
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

    outcome = ClusterOutcome()
    zone = await outcome._zone(bot, gid, cid=10, radius=2)  # type: ignore[attr-defined]
    assert [entry[0] for entry in zone] == [1, 9, 10, 11]  # 99 excluded
