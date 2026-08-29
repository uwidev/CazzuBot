"""Frog species catalog — code-defined registry, roll, typed keys/art."""

from __future__ import annotations

import random

from cazzubot.models import FrogState, FrogItemKey

from plugins.frogs import plugin as frog_plugin
from plugins.frogs.assets import FrogAsset
from plugins.frogs.items import frog_exp
from plugins.frogs.species import (
    DEFAULT_SPECIES_KEY,
    SPECIES,
    by_key,
    roll_species,
)


def test_default_species_is_basic() -> None:
    assert DEFAULT_SPECIES_KEY is FrogItemKey.BASIC
    basic = by_key(FrogItemKey.BASIC)
    assert basic is not None and basic.name == "Basic Frog"
    # the entity sheds consume data — the legacy 10/3 values moved to the
    # item definitions (basic normal/frozen give 10/3)
    assert not hasattr(basic, "consume_effect")
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
    # cluster is uncatchable-by-design: no art, but a spawn hook that
    # replaces the catchable frog at spawn time
    cluster = by_key(FrogItemKey.CLUSTER)
    assert cluster is not None and cluster.art is None
    assert cluster.spawn_effect is not None


def test_species_art_is_a_declared_asset_member_or_none() -> None:
    """The reference is the declaration: an asset cannot be misspelled.

    A species with visible art carries a :class:`FrogAsset` member; an
    uncatchable species (Cluster) deliberately carries ``None``.
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
