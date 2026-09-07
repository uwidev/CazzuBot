"""Cluster Frog — the catch behavior: catching it never grants an item;
instead one catch bursts 2–10 child Basic frogs (weighted low; 10 is a ~10%
jackpot) into nearby text channels.
"""
# driving hikari-typed helpers (member_snapshot) with FakeMember fakes
# pyright: reportArgumentType=false

from __future__ import annotations

import asyncio
import random

import hikari
import pendulum

from core.models import FrogItemKey
from core.utils import member_snapshot
import plugins.frogs.behaviors as behaviors_mod
from plugins.frogs.behaviors import ClusterBurst
from plugins.frogs.species import by_key
from tests.fakes import FakeChannel, FakeMember, InstantAsyncio


async def test_cluster_catch_bursts_basics_into_zone(
    full_bot,
    monkeypatch,
) -> None:
    """A cluster catch posts the announcement + N child Basic frogs."""
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
    monkeypatch.setattr(behaviors_mod, "asyncio", InstantAsyncio())

    cluster = by_key(FrogItemKey.CLUSTER)
    assert cluster is not None
    sent = await burst(
        bot,
        uid=123,
        member=member_snapshot(FakeMember(id=123, name="t")),
        species=cluster,
        now=pendulum.now("UTC"),
        cid=10,
        persist=30,
    )
    # children are tracked background tasks — drain the loop
    for _ in range(100):
        if len(spawned) >= 4:
            break
        await asyncio.sleep(0.01)

    assert 4 <= len(spawned) <= 6
    assert {key for _, key in spawned} == {FrogItemKey.BASIC}
    assert {cid_ for cid_, _ in spawned} <= {9, 10, 11}
    # the announcement names the catcher and is the one standalone message
    assert sent is not None
    created = bot.rest.created
    assert len(created) == 1
    msg = created[0]
    embed = msg.embeds[0]
    assert embed.title == "Cluster Frog burst!"
    # the catcher's mention + ping live on the message content (Discord
    # does not resolve pings inside embeds), not in the embed description
    assert f"<@{123}>" in msg.content
    # cluster frogs are never "caught" — the copy says the catch failed
    # but the frog burst anyway
    assert "tried to catch" in msg.content
    assert "failed" in msg.content
    assert "burst" in msg.content
    assert "caught a" not in msg.content
    # the burst outcome count is the "new count" line (there is no item
    # stack for a burst — the burst IS the catch); Random(7) drives the
    # count the same way it drives the burst's
    expected = __import__("random").Random(7).randint(4, 6)
    assert f"**`{expected}`** Basic Frogs" in msg.content
    # unpublished cluster art adds no emoji — never the literal "None"
    assert "None" not in msg.content
    # the embed is thumbnail-free (no CATCH_BANNER media) and carries no
    # mention — the mention lives on the content
    assert embed.thumbnail is None
    assert f"<@{123}>" not in (embed.description or "")
    assert "burst" in (embed.description or "")
    # least-permissive: only the catcher is pinged — no role/@everyone
    assert msg.create_kwargs["user_mentions"] == [123]
    assert msg.create_kwargs["role_mentions"] is hikari.UNDEFINED
    assert msg.create_kwargs["mentions_everyone"] is hikari.UNDEFINED


async def test_cluster_zone_ignores_non_text_and_outside_channels(
    full_bot,
) -> None:
    """The zone is text channels of the origin category within ±2.

    Non-text channels are never targets, and a text channel in another
    category does not leak into the blast even when it sits right next to
    the room in the guild-wide position order (FROG.md: ±2, roomed).
    """
    bot = full_bot
    gid = bot.config.guild_id
    guild = bot.rest.guilds[gid]
    room = 100
    for cid_, pos in ((1, 0), (9, 1), (10, 2), (11, 3)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        channel.parent_id = room
        guild.channels[cid_] = channel
    # a non-text channel in the same room is never a target
    noise = FakeChannel(id=99, guild_id=gid)
    noise.position = 9
    noise.parent_id = room
    noise.type = None
    guild.channels[99] = noise
    # an adjacent text channel in a different category would have fallen
    # inside the old guild-order ±2 (right after 11) - the room excludes it
    other = FakeChannel(id=88, guild_id=gid)
    other.position = 4
    other.parent_id = 200
    guild.channels[88] = other

    burst = ClusterBurst()
    zone = await burst._zone(bot, gid, 10)  # type: ignore[attr-defined]
    zone_ids = [entry[0] for entry in zone]
    assert zone_ids == [1, 9, 10, 11]
    assert 88 not in zone_ids
    assert 99 not in zone_ids


async def test_cluster_zone_uncategorized_channels_form_one_room(
    full_bot,
) -> None:
    """A catch in an uncategorized channel bursts uncategorized text
    channels around it - categorized channels are outside that room.
    """
    bot = full_bot
    gid = bot.config.guild_id
    guild = bot.rest.guilds[gid]
    for cid_, pos in ((2, 0), (3, 1)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        guild.channels[cid_] = channel  # parent stays None
    cat = FakeChannel(id=4, guild_id=gid)
    cat.position = 2
    cat.parent_id = 300
    guild.channels[4] = cat

    burst = ClusterBurst()
    zone = await burst._zone(bot, gid, 2)  # type: ignore[attr-defined]
    assert [entry[0] for entry in zone] == [2, 3]


async def test_cluster_burst_targets_stay_in_the_origin_category(
    full_bot,
    monkeypatch,
) -> None:
    """The burst children spawn only inside the origin room - a sensitive
    channel in its own category, adjacent in guild position, is never hit.
    """
    bot = full_bot
    gid = bot.config.guild_id
    guild = bot.rest.guilds[gid]
    room = 100
    for cid_, pos in ((98, 1), (99, 2), (100, 3)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        channel.parent_id = room
        guild.channels[cid_] = channel
    # a staff-style channel in another category right after the room in
    # the guild-wide position order (old ±2-by-position could reach it)
    staff = FakeChannel(id=777, guild_id=gid)
    staff.position = 4
    staff.parent_id = 200
    guild.channels[777] = staff

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
    monkeypatch.setattr(behaviors_mod, "asyncio", InstantAsyncio())

    cluster = by_key(FrogItemKey.CLUSTER)
    assert cluster is not None
    sent = await burst(
        bot,
        uid=123,
        member=member_snapshot(FakeMember(id=123, name="t")),
        species=cluster,
        now=pendulum.now("UTC"),
        cid=99,
        persist=30,
    )
    for _ in range(100):
        if len(spawned) >= 4:
            break
        await asyncio.sleep(0.01)

    assert sent is not None
    assert 2 <= len(spawned) <= 10
    assert {key for _, key in spawned} == {FrogItemKey.BASIC}
    cids = {cid_ for cid_, _ in spawned}
    assert cids <= {98, 99, 100}
    assert 777 not in cids


def test_burst_spawn_count_weights_shape() -> None:
    """The burst-size roll spans 2-10, weighted low: 3-4 are the most
    common amounts, the big-but-not-jackpot blasts are rare, and 10 is
    a ~10% jackpot (the weight tuple sums to 100)."""
    weights = behaviors_mod._BURST_COUNT_WEIGHTS
    counts = tuple(
        range(
            behaviors_mod._BURST_MIN_COUNT,
            behaviors_mod._BURST_MAX_COUNT + 1,
        )
    )
    assert len(weights) == len(counts)
    assert sum(weights) == 100  # entries read as approximate percentages

    rng = random.Random(1234)
    rolls = [behaviors_mod._burst_spawn_count(rng) for _ in range(20000)]
    assert min(rolls) == behaviors_mod._BURST_MIN_COUNT
    assert max(rolls) == behaviors_mod._BURST_MAX_COUNT
    p10 = rolls.count(behaviors_mod._BURST_MAX_COUNT) / len(rolls)
    p34 = sum(rolls.count(n) for n in (3, 4)) / len(rolls)
    p9 = rolls.count(9) / len(rolls)
    assert 0.08 <= p10 <= 0.13  # the ~10% jackpot
    assert p34 >= 0.35  # 3-4 are the common amounts
    assert p9 < 0.06  # big non-jackpot blasts stay rare


async def test_cluster_burst_jackpot_spawns_ten(
    full_bot,
    monkeypatch,
) -> None:
    """The burst size comes from the weighted 2-10 roll end to end - a
    fixed-choices stub (always 10) makes a jackpot blast of ten children."""
    bot = full_bot
    gid = bot.config.guild_id
    guild = bot.rest.guilds[gid]
    room = 100
    for cid_, pos in ((98, 1), (99, 2), (100, 3)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        channel.parent_id = room
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

    class _AlwaysTen(random.Random):
        """A Random whose choices always roll the jackpot (10)."""

        def choices(
            self, population, weights=None, *, cum_weights=None, k=1
        ) -> list[int]:
            return [10] * k

    burst = ClusterBurst()
    burst.spawn_impl = fake_spawn
    monkeypatch.setattr(behaviors_mod, "random", _AlwaysTen(7))
    monkeypatch.setattr(behaviors_mod, "asyncio", InstantAsyncio())

    cluster = by_key(FrogItemKey.CLUSTER)
    assert cluster is not None
    sent = await burst(
        bot,
        uid=123,
        member=member_snapshot(FakeMember(id=123, name="t")),
        species=cluster,
        now=pendulum.now("UTC"),
        cid=99,
        persist=30,
    )
    prev = -1
    for _ in range(200):
        if len(spawned) == prev and len(spawned) > 0:
            break
        prev = len(spawned)
        await asyncio.sleep(0.01)

    assert sent is not None
    assert len(spawned) == 10  # the forced jackpot blast
    assert {key for _, key in spawned} == {FrogItemKey.BASIC}
    assert {cid_ for cid_, _ in spawned} <= {98, 99, 100}


async def test_burst_embed_thumbnail_references_banner_asset(
    full_bot,
) -> None:
    """The burst announcement embed's thumbnail references the CATCH_BANNER
    media asset (plugins/assets/caught.png) when published — like the
    grant capture embed, not a hardcoded image."""
    await full_bot.db.execute(
        "UPDATE asset SET url = ? WHERE key = ?",
        "https://cdn.example/catch_banner.png",
        "FrogAsset.CATCH_BANNER",
    )
    cluster = by_key(FrogItemKey.CLUSTER)
    assert cluster is not None
    embed = await behaviors_mod._burst_embed(full_bot, cluster, 5)
    assert embed.thumbnail is not None
    assert embed.thumbnail.url == "https://cdn.example/catch_banner.png"
