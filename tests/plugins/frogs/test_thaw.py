"""Frog thaw service — the risky cash-out of frozen season-end trophies.

``thaw_frogs`` rolls each frozen unit independently at ``THAW_CHANCE``:
a survival restores the species' normal frog, a failure leaves Frog Remains.
RNG is injectable (``rng``) so these tests force success, failure and mixed
outcomes, and assert the exact ledger moves and the balance guard.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.models import FrogItemKey, FrogState
from plugins.frogs import db as frog_db
from plugins.frogs import thaw


@dataclass
class _Queued:
    """A deterministic rng: ``random()`` pops the next queued value."""

    values: list[float]

    def random(self) -> float:
        if not self.values:
            return 0.0  # exhausted — treat as always-survive
        return self.values.pop(0)


def test_frozen_species_of_parses_only_frozen_frog_ids() -> None:
    """Only ``frog:<species>:frozen`` is a thawable frozen frog."""
    assert thaw.frozen_species_of("frog:pog:frozen") is FrogItemKey.POG
    assert thaw.frozen_species_of("frog:basic:frozen") is FrogItemKey.BASIC
    # everything else is not a frozen frog
    assert thaw.frozen_species_of("frog:pog:normal") is None
    assert thaw.frozen_species_of("remains") is None
    assert thaw.frozen_species_of("frog:cluster:frozen") is None
    assert thaw.frozen_species_of("garbage") is None


async def test_thaw_all_survive(bot: CazzuBot) -> None:
    """rng < chance always: every unit restores the species' normal frog."""
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.POG, FrogState.FROZEN, 3
    )

    outcome = await thaw.thaw_frogs(
        bot, 1, FrogItemKey.POG, 3, rng=_Queued([0.0, 0.0, 0.0])
    )

    assert outcome == thaw.ThawOutcome(
        species=FrogItemKey.POG, attempted=3, survived=3, remains=0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.POG, FrogState.FROZEN
        )
        == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.POG, FrogState.NORMAL
        )
        == 3
    )
    assert await bot.inventory.get(1, "remains") == 0


async def test_thaw_all_fail(bot: CazzuBot) -> None:
    """rng >= chance always: every unit becomes Frog Remains."""
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.CLASSY, FrogState.FROZEN, 2
    )

    outcome = await thaw.thaw_frogs(
        bot, 1, FrogItemKey.CLASSY, 2, rng=_Queued([0.9, 0.9])
    )

    assert outcome == thaw.ThawOutcome(
        species=FrogItemKey.CLASSY, attempted=2, survived=0, remains=2
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.CLASSY, FrogState.FROZEN
        )
        == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.CLASSY, FrogState.NORMAL
        )
        == 0
    )
    assert await bot.inventory.get(1, "remains") == 2


async def test_thaw_mixed_outcome(bot: CazzuBot) -> None:
    """A mixed roll: survivors restore, failures become remains, exactly."""
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.FROGGERS, FrogState.FROZEN, 4
    )

    outcome = await thaw.thaw_frogs(
        bot, 1, FrogItemKey.FROGGERS, 4, rng=_Queued([0.1, 0.9, 0.4, 0.8])
    )

    assert outcome == thaw.ThawOutcome(
        species=FrogItemKey.FROGGERS, attempted=4, survived=2, remains=2
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.FROGGERS, FrogState.FROZEN
        )
        == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.FROGGERS, FrogState.NORMAL
        )
        == 2
    )
    assert await bot.inventory.get(1, "remains") == 2


async def test_thaw_merges_into_existing_stacks(bot: CazzuBot) -> None:
    """Survivors add to any normal stack; remains to any remains pile."""
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.BASIC, FrogState.FROZEN, 2
    )
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.BASIC, FrogState.NORMAL, 2
    )
    await bot.inventory.add(1, "remains", 1)

    # first thaw: survives (merges 2+1=3 normal); second: fails (1+1 remains)
    await thaw.thaw_frogs(bot, 1, FrogItemKey.BASIC, 1, rng=_Queued([0.0]))
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.BASIC, FrogState.FROZEN
        )
        == 1
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.BASIC, FrogState.NORMAL
        )
        == 3
    )
    await thaw.thaw_frogs(bot, 1, FrogItemKey.BASIC, 1, rng=_Queued([1.0]))
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.BASIC, FrogState.FROZEN
        )
        == 0
    )
    assert await bot.inventory.get(1, "remains") == 2


async def test_thaw_insufficient_balance_raises(bot: CazzuBot) -> None:
    """Thawing more than held fails loudly, before any ledger move."""
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.POG, FrogState.FROZEN, 1
    )

    with pytest.raises(UserInputError, match="only have"):
        await thaw.thaw_frogs(
            bot, 1, FrogItemKey.POG, 2, rng=_Queued([0.0])
        )

    # nothing moved
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.POG, FrogState.FROZEN
        )
        == 1
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.POG, FrogState.NORMAL
        )
        == 0
    )
    assert await bot.inventory.get(1, "remains") == 0
