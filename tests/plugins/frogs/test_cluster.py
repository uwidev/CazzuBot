"""Cluster Frog — the catch behavior: catching it never grants an item;
instead one catch bursts 4–6 child Basic frogs into nearby text channels.
"""
# driving hikari-typed helpers (member_snapshot) with FakeMember fakes
# pyright: reportArgumentType=false

from __future__ import annotations

import asyncio

import hikari
import pendulum

from cazzubot.models import FrogItemKey
from cazzubot.utils import member_snapshot
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
