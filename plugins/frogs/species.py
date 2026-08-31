"""Frog species catalog — defined entirely in code.

The ``SPECIES`` registry is the single source of truth: names, rarity,
weights and art all live here (no catalog table — a DB row would create a
proxy interface for tuning and balancing, which is exactly the friction we
want to avoid). Tuning a species = editing this file and restarting
(``/plugin reload frogs`` picks it up too).

Keys and references are **typed, never strings**: ``SpeciesKey`` is the
enum of valid species (the LSP completes it; a typo cannot compile), and
a species' ``art`` is a :class:`FrogAsset` member when it has visible art
(``None`` for an uncatchable species like Cluster) — the declaration IS
the reference, so an undeclared asset cannot be spelled. Strings exist only
at the data boundary (DB columns, slash options, custom ids), converted
to/from the enums there.

Outcomes are referenced by **payload instance**, not by key string: a
species carries its configured ``catch_outcome`` payload (see
``outcomes.py``), so the same outcome class is reusable with different
values and a species never carries fields for outcomes it doesn't use.
Consumption is *item-owned* — see ``items.py`` — so the entity carries
no consume fields.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from cazzubot.models import FrogItemKey

from .assets import FrogAsset
from .outcomes import ClusterPayload, OutcomePayload

DEFAULT_SPECIES_KEY = FrogItemKey.BASIC


@dataclass(frozen=True, slots=True)
class Species:
    """One species — values are code, swappable only by editing them.

    The **entity**: what a frog *is* as a world/spawn object (its name,
    rarity, spawn weight, art, and what happens on catch). What consuming
    a caught frog does is deliberately NOT here: consumption is
    **item-owned** (owner 2026-08-28 — the item composes, outcomes
    invoke). The matching :class:`Item` in ``items.py`` grants exp from
    its oracle and composes the outcomes it applies
    (``items.py::_SPECIES_OUTCOMES``), so a species carries no consume
    declaration. What a caught frog becomes as an inventory object (its
    item_id, icon, consume behavior) lives on that item, not here.

    ``art`` is optional — an uncatchable species (Cluster) has no visible
    art. ``catch_outcome`` handles the catch side; ``spawn_outcome``
    replaces the catchable frog at spawn time (Cluster's explosion).
    """

    key: FrogItemKey
    name: str
    rarity: str
    description: str
    spawn_weight: float
    catch_outcome: OutcomePayload | None
    spawn_outcome: OutcomePayload | None
    art: FrogAsset | None


SPECIES: tuple[Species, ...] = (
    Species(
        key=FrogItemKey.BASIC,
        name="Basic Frog",
        rarity="common",
        description="The most normalest frog of them all.",
        spawn_weight=1000.0,
        catch_outcome=None,
        spawn_outcome=None,
        art=FrogAsset.FROG_BASIC,
    ),
    Species(
        key=FrogItemKey.POG,
        name="Pog Frog",
        rarity="uncommon",
        description="A frog with a pog.",
        spawn_weight=200.0,
        catch_outcome=None,
        spawn_outcome=None,
        art=FrogAsset.FROG_POG,
    ),
    Species(
        key=FrogItemKey.FROGGERS,
        name="Froggers Frog",
        rarity="rare",
        description="A frog with a poggers.",
        spawn_weight=50.0,
        catch_outcome=None,
        spawn_outcome=None,
        art=FrogAsset.FROG_FROGGERS,
    ),
    Species(
        key=FrogItemKey.CLASSY,
        name="Classy Frog",
        rarity="rare",
        description="A frog with rather refined tastes.",
        spawn_weight=200.0,
        catch_outcome=None,
        spawn_outcome=None,
        art=FrogAsset.FROG_CLASSY,
    ),
    Species(
        key=FrogItemKey.CLUSTER,
        name="Cluster Frog",
        rarity="special",
        description="Be careful with this one… she's… spawning!",
        spawn_weight=300.0,
        catch_outcome=None,
        spawn_outcome=ClusterPayload(),
        art=None,
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
