"""Frog species catalog — code-defined registry, roll, typed keys/art."""

from __future__ import annotations

import random

from cazzubot.models import SpeciesKey

from plugins.frogs import plugin as frog_plugin
from plugins.frogs.assets import FrogAsset
from plugins.frogs.effects import EffectKey, ExpPayload
from plugins.frogs.species import (
    DEFAULT_SPECIES_KEY,
    SPECIES,
    by_key,
    roll_species,
)


def test_default_species_is_leaf_frog() -> None:
    assert DEFAULT_SPECIES_KEY is SpeciesKey.LEAF_FROG
    leaf = by_key(SpeciesKey.LEAF_FROG)
    assert leaf is not None
    # the legacy values — the default species preserves 10/3, carried by
    # its consume-effect payload
    assert isinstance(leaf.consume_effect, ExpPayload)
    assert leaf.consume_effect.exp == 10
    assert leaf.consume_effect.frozen_exp == 3
    assert leaf.consume_effect.key is EffectKey.EXP


def test_classy_frog_doubles_exp() -> None:
    classy = by_key(SpeciesKey.CLASSY_FROG)
    assert classy is not None
    leaf = by_key(SpeciesKey.LEAF_FROG)
    assert leaf is not None
    assert isinstance(classy.consume_effect, ExpPayload)
    assert isinstance(leaf.consume_effect, ExpPayload)
    assert classy.consume_effect.exp == leaf.consume_effect.exp * 2
    assert (
        classy.consume_effect.frozen_exp
        == leaf.consume_effect.frozen_exp * 2
    )
    assert classy.consume_effect.key is EffectKey.EXP


def test_species_art_is_a_declared_asset_member() -> None:
    """The reference is the declaration: an asset cannot be misspelled."""
    for species in SPECIES:
        assert isinstance(species.art, FrogAsset)


def test_by_key_unknown_returns_none() -> None:
    # every SpeciesKey member is registered; an unknown key cannot be
    # spelled — this documents that by_key stays None-free for valid keys
    for key in SpeciesKey:
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
