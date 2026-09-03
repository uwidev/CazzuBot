"""Frog species catalog — defined entirely in code.

The ``SPECIES`` registry is the single source of truth: names, rarity,
weights and art live here (no catalog table). A species is a **mob**: its
declaration composes its own behavior as code — the ``catch`` hook (what
happens when the frog is caught; nothing by default). Capturing a frog
grants the item ONLY when the catch behavior does it; the species itself is
never an inventory item (items live in ``items.py``).

Keys and references are **typed, never strings**: ``FrogItemKey`` is the
enum of valid species; a species' ``art`` is a :class:`FrogAsset` member
when it has visible art (``None`` for Cluster) — the declaration IS the
reference, so an undeclared asset cannot be spelled. Strings exist only at
the data boundary (DB columns, slash options, custom ids), converted to and
from the enums there.

Behavior helpers live beside the species that uses them
(``plugins/frogs/behaviors.py``): the four item-granting frogs compose the
shared ``grant_catch``; Cluster composes ``ClusterBurst`` — catching it
never grants an item, it bursts into Basic Frogs nearby instead.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from cazzubot.models import FrogItemKey

from .assets import FrogAsset
from .behaviors import ClusterBurst, grant_catch

DEFAULT_SPECIES_KEY = FrogItemKey.BASIC

# the one shape every species behavior has: async code running with the bot
# plus whatever context it needs (the behavior picks its own kwargs)
Behavior = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Species:
    """One mob — its behavior is the code it references.

    ``catch`` is the capture hook (None: nothing happens on capture —
    explicit per design; the item-granting species compose
    :func:`grant_catch`, Cluster composes :class:`ClusterBurst`). Helpers a
    behavior needs live beside that behavior (see ``behaviors.py``).

    What a caught frog becomes as an inventory object (its item_id, icon,
    consume behavior) lives on the matching :class:`Item` in ``items.py``,
    not here — consumption is item-owned.
    """

    key: FrogItemKey
    name: str
    rarity: str
    description: str
    spawn_weight: float
    catch: Behavior | None
    art: FrogAsset | None


SPECIES: tuple[Species, ...] = (
    Species(
        key=FrogItemKey.BASIC,
        name="Basic Frog",
        rarity="common",
        description="The most normalest frog of them all.",
        spawn_weight=1000.0,
        catch=grant_catch,
        art=FrogAsset.FROG_BASIC,
    ),
    Species(
        key=FrogItemKey.POG,
        name="Pog Frog",
        rarity="uncommon",
        description="A frog with a pog.",
        spawn_weight=200.0,
        catch=grant_catch,
        art=FrogAsset.FROG_POG,
    ),
    Species(
        key=FrogItemKey.FROGGERS,
        name="Froggers Frog",
        rarity="rare",
        description="A frog with a poggers.",
        spawn_weight=50.0,
        catch=grant_catch,
        art=FrogAsset.FROG_FROGGERS,
    ),
    Species(
        key=FrogItemKey.CLASSY,
        name="Classy Frog",
        rarity="rare",
        description="A frog with rather refined tastes.",
        spawn_weight=200.0,
        catch=grant_catch,
        art=FrogAsset.FROG_CLASSY,
    ),
    Species(
        key=FrogItemKey.CLUSTER,
        name="Cluster Frog",
        rarity="special",
        description="Be careful with this one… she's… spawning!",
        spawn_weight=300.0,
        catch=ClusterBurst(),  # the burst IS the catch — no item is granted
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
