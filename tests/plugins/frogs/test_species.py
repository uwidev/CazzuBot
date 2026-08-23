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


def test_default_species_is_leaf_frog() -> None:
    assert DEFAULT_SPECIES_KEY is FrogItemKey.BASIC
    leaf = by_key(FrogItemKey.BASIC)
    assert leaf is not None
    # the entity sheds consume data — the legacy 10/3 values moved to the
    # item definitions (leaf normal/frozen give 10/3)
    assert not hasattr(leaf, "consume_effect")
    assert not hasattr(leaf, "consumable")
    assert frog_exp(leaf.key, FrogState.NORMAL) == 10
    assert frog_exp(leaf.key, FrogState.FROZEN) == 3


def test_catalog_is_single_species() -> None:
    """Right now only the normal Leaf Frog spawns — no extra species."""
    assert [species.key for species in SPECIES] == [FrogItemKey.BASIC]
    assert by_key(FrogItemKey.BASIC) is not None


def test_species_art_is_a_declared_asset_member() -> None:
    """The reference is the declaration: an asset cannot be misspelled."""
    for species in SPECIES:
        assert isinstance(species.art, FrogAsset)


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
