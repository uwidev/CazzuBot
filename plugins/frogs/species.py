"""Frog species catalog — defined entirely in code.

The ``SPECIES`` registry is the single source of truth: names, rarity,
weights and art all live here (no catalog table — a DB row would create a
proxy interface for tuning and balancing, which is exactly the friction we
want to avoid). Tuning a species = editing this file and restarting
(``/plugin reload frogs`` picks it up too).

Keys and references are **typed, never strings**: ``SpeciesKey`` is the
enum of valid species (the LSP completes it; a typo cannot compile), and
a species' ``art`` is a :class:`FrogAsset` member — the declaration IS the
reference, so an undeclared asset cannot be spelled. Strings exist only
at the data boundary (DB columns, slash options, custom ids), converted
to/from the enums there.

Effects are referenced by **payload instance**, not by key string: a
species carries its configured ``catch_effect`` payload (see ``effects.py``),
so the same effect class is reusable with different values and a species
never carries fields for effects it doesn't use. Consumption is *item-owned*
— see ``items.py`` — so the entity carries no consume fields.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from cazzubot.models import FrogItemKey

from .assets import FrogAsset
from .effects import EffectPayload

DEFAULT_SPECIES_KEY = FrogItemKey.BASIC


@dataclass(frozen=True, slots=True)
class Species:
    """One species — values are code, swappable only by editing them.

    The **entity**: what a frog *is* as a world/spawn object (its name,
    rarity, spawn weight, art, and what happens on catch). What a caught
    frog becomes as an inventory object (its item_id, icon, consume
    behavior) lives on the matching :class:`Item` in ``items.py`` — not
    here.
    """

    key: FrogItemKey
    name: str
    rarity: str
    description: str
    spawn_weight: float
    catch_effect: EffectPayload | None
    art: FrogAsset


SPECIES: tuple[Species, ...] = (
    Species(
        key=FrogItemKey.BASIC,
        name="Leaf Frog",
        rarity="common",
        description="A perfectly ordinary frog.",
        spawn_weight=1.0,
        catch_effect=None,
        art=FrogAsset.FROG_BASIC,
    ),
)

_BY_KEY: dict[FrogItemKey, Species] = {
    species.key: species for species in SPECIES
}


def by_key(key: FrogItemKey) -> Species | None:
    """The species for ``key`` (None when unknown)."""
    return _BY_KEY.get(key)


def roll_species(rng: random.Random | None = None) -> Species:
    """Pick a species by ``spawn_weight``; ``rng`` seeds the roll for tests."""
    chooser = rng or random
    return chooser.choices(
        SPECIES, weights=[species.spawn_weight for species in SPECIES]
    )[0]
