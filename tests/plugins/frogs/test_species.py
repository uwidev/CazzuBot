"""Frog species catalog — code-defined registry, roll, typed keys/art."""
# driving hikari-typed helpers (member_snapshot) with FakeMember fakes
# pyright: reportArgumentType=false

from __future__ import annotations

import random

import pendulum

from cazzubot.models import FrogItemKey, FrogState
from cazzubot.utils import member_snapshot

from plugins.frogs import plugin as frog_plugin
from plugins.frogs.assets import FrogAsset
from plugins.frogs.items import frog_exp
from plugins.frogs.species import (
    DEFAULT_SPECIES_KEY,
    SPECIES,
    Species,
    by_key,
    roll_species,
)
from tests.fakes import FakeMember


def test_default_species_is_basic() -> None:
    assert DEFAULT_SPECIES_KEY is FrogItemKey.BASIC
    basic = by_key(FrogItemKey.BASIC)
    assert basic is not None and basic.name == "Basic Frog"
    # the entity sheds consume data — the legacy 10/3 values moved to the
    # item definitions (basic normal/frozen give 10/3)
    assert not hasattr(basic, "consume_outcome")
    assert not hasattr(basic, "consumable")
    assert frog_exp(basic.key, FrogState.NORMAL) == 10
    assert frog_exp(basic.key, FrogState.FROZEN) == 3


def test_species_registry_has_frogmd_five() -> None:
    """FROG.md's five species with their spawn weights are registered."""
    keys = {species.key for species in SPECIES}
    assert keys == {
        FrogItemKey.BASIC,
        FrogItemKey.POG,
        FrogItemKey.FROGGERS,
        FrogItemKey.CLASSY,
        FrogItemKey.CLUSTER,
    }
    weights = {species.key: species.spawn_weight for species in SPECIES}
    # FROG.md weights (relative)
    assert weights[FrogItemKey.BASIC] == 1000.0
    assert weights[FrogItemKey.POG] == 200.0
    assert weights[FrogItemKey.FROGGERS] == 50.0
    assert weights[FrogItemKey.CLASSY] == 200.0
    assert weights[FrogItemKey.CLUSTER] == 300.0
    # cluster is catchable-by-design: it spawns like any frog, but its
    # catch bursts into Basics instead of granting an item
    from plugins.frogs.behaviors import ClusterBurst

    cluster = by_key(FrogItemKey.CLUSTER)
    assert cluster is not None and cluster.art is FrogAsset.FROG_CLUSTER
    assert isinstance(cluster.catch, ClusterBurst)
    assert not hasattr(cluster, "spawn")  # the spawn-hook shape is gone


def test_species_art_is_a_declared_asset_member_or_none() -> None:
    """The reference is the declaration: an asset cannot be misspelled.

    A species with visible art carries a :class:`FrogAsset` member; a
    species without visible art (Cluster) deliberately carries ``None``.
    """
    for species in SPECIES:
        if species.art is not None:
            assert isinstance(species.art, FrogAsset)


def test_roll_species_respects_weights() -> None:
    """The weighted roll lands near the FROG.md distribution."""
    rng = random.Random(42)
    rolls = [roll_species(rng).key for _ in range(2000)]
    basic = rolls.count(FrogItemKey.BASIC) / len(rolls)
    froggers = rolls.count(FrogItemKey.FROGGERS) / len(rolls)
    assert 0.50 < basic < 0.65  # 1000/1750 ≈ 0.571 within noise
    assert 0.01 < froggers < 0.08  # 50/1750 ≈ 0.029


def test_by_key_unknown_returns_none() -> None:
    # every SpeciesKey member is registered; an unknown key cannot be
    # spelled — this documents that by_key stays None-free for valid keys
    for key in FrogItemKey:
        assert by_key(key) is not None, key


def test_roll_species_seeded_is_deterministic() -> None:
    rng = random.Random(42)
    first = roll_species(rng)
    rng2 = random.Random(42)
    second = roll_species(rng2)
    assert first.key == second.key
    assert first in SPECIES


def test_roll_species_only_returns_registered() -> None:
    for _ in range(50):
        assert roll_species(random.Random()).key in {
            species.key for species in SPECIES
        }


def test_species_are_defined_in_code_only() -> None:
    """No catalog table: the registry is the single source of truth."""
    assert not any(
        statement.startswith("CREATE TABLE IF NOT EXISTS frog_species")
        for statement in frog_plugin.schema
    )


async def test_species_grant_catch_adds_item(full_bot) -> None:
    """The shared grant_catch behavior composes into a species: +1 item."""
    from plugins.frogs.behaviors import grant_catch

    species = by_key(FrogItemKey.POG)
    assert species is not None
    member = member_snapshot(FakeMember(id=123, name="t"))
    await grant_catch(
        full_bot,
        uid=123,
        member=member,
        species=species,
        now=pendulum.now("UTC"),
        cid=99,
    )
    assert await full_bot.inventory.get(123, "frog:pog:normal") == 1


async def test_catch_none_grants_nothing(full_bot, monkeypatch) -> None:
    """A species with ``catch=None`` grants no item on capture.

    The capture accounting (log + counter + event) still runs — ``catch``
    only gates the species' own behavior, not the flow's ledger.
    """
    from tests.fakes import (
        FakeInteraction,
        FakeMenuContext,
        menu_button,
    )

    from plugins.frogs import factory
    from plugins.frogs.events import FrogCapturedEvent
    from plugins.frogs.species import by_key as real_by_key

    no_catch = Species(
        key=FrogItemKey.BASIC,
        name="Shy Frog",
        rarity="common",
        description="Won't let you keep it.",
        spawn_weight=1.0,
        catch=None,
        art=None,
    )
    monkeypatch.setattr(
        factory,
        "by_key",
        lambda key: (
            no_catch if key is FrogItemKey.BASIC else real_by_key(key)
        ),
    )
    received: list[FrogCapturedEvent] = []

    async def on_captured(event: FrogCapturedEvent) -> None:
        received.append(event)

    full_bot.events.on(FrogCapturedEvent, on_captured)

    menu = factory.FrogCatchMenu(
        full_bot, 99, FrogItemKey.BASIC, persist=30
    )
    mctx = FakeMenuContext(
        FakeInteraction(
            id=1, member=FakeMember(id=424242, name="t"), channel_id=99
        )
    )
    await menu_button(menu).callback(mctx)

    assert await full_bot.inventory.get(424242, "frog:basic:normal") == 0
    assert (
        await full_bot.db.fetchval(
            "SELECT capture FROM member_frog WHERE uid = 424242"
        )
        == 1
    )
    assert len(received) == 1
    assert received[0].uid == 424242
