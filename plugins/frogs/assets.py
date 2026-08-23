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

    LEAF_FROG = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/leaf_frog.png"
    )
    # the capture embed's thumbnail — a media image, CDN-published
    CATCH_BANNER = AssetSpec(
        kind=AssetKind.SPECIES, path="assets/catch_banner.png"
    )
