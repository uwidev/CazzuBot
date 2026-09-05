"""Frog thaw — the risky cash-out of frozen season-end trophies.

At the season rollover every frog freezes in place (``db.season_reset_frogs``),
and frozen frogs are non-consumable. The only way out is the thaw gamble:
per unit, ``THAW_CHANCE`` (50%) restores the species' *normal* frog — full
exp and statuses again, re-freezing at the next rollover if unconsumed —
and the rest leaves behind "Frog Remains" (id ``remains``, a small exp
floor; ``items._REMAINS_EXP``).

This service owns the odds and the ledger moves; the command edge
(``/inventory thaw``) is presentation. RNG is injectable (``rng``), mirroring
``species.roll_species``, so tests force success/failure; the module-level
``random`` is the production source.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from cazzubot import inventory
from cazzubot.errors import UserInputError
from cazzubot.models import FrogItemKey, FrogState

from . import db as frog_db

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot


class _RandomLike(Protocol):
    """Anything with a ``random() -> float`` — ``random.Random`` (prod,
    module-level) or a deterministic test stub (see tests/test_thaw.py)."""

    def random(self) -> float: ...


# the per-unit thaw survival chance. Deliberately flat (no pity/streak —
# an explicit trial run); kept in sync with items._thaw_field()'s prose.
THAW_CHANCE = 0.5

# the failed-thaw consolation item id (deliberately NOT ``frog:``-prefixed,
# so frog totals never count it — see items._consume_remains).
REMAINS_ITEM = "remains"


@dataclass(frozen=True, slots=True)
class ThawOutcome:
    """The tally of one thaw request: how many survived vs became remains."""

    species: FrogItemKey
    attempted: int
    survived: int
    remains: int


def frozen_species_of(item_id: str) -> FrogItemKey | None:
    """The species behind a frozen-frog item id, or None.

    Accepts ``frog:<species>:frozen``. Anything else — non-frog, non-frozen,
    Cluster (no item exists; its stack could never be held) or the
    ``remains`` id — is not a thawable frozen frog.
    """
    try:
        item = frog_db.FrogItem.parse(item_id)
    except ValueError:
        return None
    if item.state is not FrogState.FROZEN:
        return None
    if item.species is FrogItemKey.CLUSTER:
        return None
    return item.species


async def thaw_frogs(
    bot: "CazzuBot",
    uid: int,
    species_key: FrogItemKey,
    amount: int,
    *,
    rng: _RandomLike | None = None,
) -> ThawOutcome:
    """Thaw ``amount`` frozen frogs of ``species_key``, rolling each unit.

    Validates the frozen balance (else ``UserInputError``), then within one
    transaction: deduct the frozen stack, add the species' normal frog per
    survival, and add ``Frog Remains`` per failure. Returns the tally —
    the caller (``/inventory thaw``) renders it.
    """
    held = await frog_db.get_inventory(
        bot.db, uid, species_key, FrogState.FROZEN
    )
    if held < amount:
        raise UserInputError(
            f"You only have **{held}** frozen frog(s) to thaw."
        )

    chooser = rng or random
    survived = 0
    async with bot.db.transaction():
        await frog_db.modify_inventory(
            bot.db, uid, species_key, FrogState.FROZEN, -amount
        )
        for _ in range(amount):
            if chooser.random() < THAW_CHANCE:
                survived += 1
        if survived:
            await frog_db.modify_inventory(
                bot.db, uid, species_key, FrogState.NORMAL, survived
            )
        fails = amount - survived
        if fails:
            await inventory.modify(bot.db, uid, REMAINS_ITEM, fails)

    return ThawOutcome(
        species=species_key,
        attempted=amount,
        survived=survived,
        remains=fails,
    )
