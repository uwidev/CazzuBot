"""Frog assets — the declaration IS the reference.

Each member's value is an ``AssetSpec``; the registry key is derived from
the enum identity (``cazzubot.assets.asset_key``), never hand-written.
Referencing an asset = naming a member, so an undeclared asset cannot be
spelled.
"""

from __future__ import annotations

from enum import Enum

from cazzubot.assets import AssetKind, AssetSpec


class FrogAsset(Enum):
    """Every asset the frogs plugin declares."""

    FROG_BASIC = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog-basic.png"
    )

    FROG_BASIC_FROZEN = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog-basic-frozen.png"
    )

    FROG_POG = AssetSpec(kind=AssetKind.EMOJI, path="assets/frog-pog.png")

    FROG_FROGGERS = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog-froggers.png"
    )

    FROG_CLASSY = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog-classy.png"
    )

    # the capture embed's thumbnail — a media image, CDN-published
    CATCH_BANNER = AssetSpec(
        kind=AssetKind.IMAGE, path="assets/caught.png"
    )
