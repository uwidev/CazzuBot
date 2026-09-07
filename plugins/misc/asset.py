"""Misc plugin assets — shared cirno emojis + the randomized footer icon.

The misc plugin hosts the bot's shared brand emojis (the cirno reaction
shots in ``assets/``) so any surface can use them without owning their
files. Each member's value is an ``AssetSpec``; the registry key is
derived from the enum identity (``cazzubot.assets.asset_key``), never
hand-written. A member IS the reference — an undeclared asset cannot be
spelled (see ``cazzubot/assets.py``).

Embed surfaces that cycle a footer tip (``cazzubot.tips``) pull their
footer **icon** from here: :func:`random_footer_icon` mirrors
``tips.get_tip``'s random-per-render behavior, so repeated embeds cycle
through the published cirno emojis instead of pinning one icon.
"""

from __future__ import annotations

import random
from enum import Enum
from typing import TYPE_CHECKING

from cazzubot.assets import AssetKind, AssetSpec

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot


class MiscAsset(Enum):
    """Every asset the misc plugin declares (all cirno reaction shots)."""

    CIRNO_DRUNK = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/cirnoDrunk.png"
    )

    CIRNO_NERD = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/cirnoNerd.png"
    )

    CIRNO_READ = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/cirnoRead.png"
    )

    CIRNO_SIP_CUP = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/cirnoSipCup.png"
    )

    CIRNO_SIP_DRONK = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/cirnoSipDronk.png"
    )

    CIRNO_SIP_JUICE = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/cirnoSipJuice.png"
    )

    CIRNO_SNOWMAN = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/cirnoSnowman.png"
    )


async def random_footer_icon(bot: "CazzuBot") -> str | None:
    """One random published cirno emoji's CDN URL, for embed footer icons.

    Each call picks a fresh random ``MiscAsset`` member — same
    random-per-render contract as ``tips.get_tip`` for footer text — and
    resolves its published emoji to the CDN URL a footer icon needs
    (``bot.assets.thumbnail_for``: ``<:name:id>`` → ``cdn.discordapp.com``,
    media pass through). ``None`` while the asset is unpublished (no asset
    guild configured or a pending re-sync): callers skip the icon then and
    keep their text-only tip footer.
    """
    asset = random.choice(tuple(MiscAsset))
    return await bot.assets.thumbnail_for(asset)
