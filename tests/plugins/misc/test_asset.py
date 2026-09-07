"""Misc plugin — shared asset declarations and the randomized footer icon."""

from __future__ import annotations

from pathlib import Path

from cazzubot.assets import AssetKind
from plugins.misc import MiscPlugin
from plugins.misc.asset import MiscAsset, random_footer_icon

# tests/plugins/misc/test_asset.py → parents[3] is the repo root
_PLUGIN_DIR = Path(__file__).parents[3] / "plugins" / "misc"


def test_every_asset_is_an_emoji() -> None:
    """All misc assets register as EMOJI (guild emojis, not CDN media)."""
    kinds = {asset.value.kind for asset in MiscAsset}
    assert kinds == {AssetKind.EMOJI}


def test_every_asset_maps_to_a_real_file() -> None:
    """Each member's declared file exists inside plugins/misc/assets/."""
    for asset in MiscAsset:
        assert (_PLUGIN_DIR / asset.value.path).is_file(), asset


def test_members_cover_every_file_in_the_assets_folder() -> None:
    """Registration is complete: enum members ↔ files on disk, 1:1."""
    declared = sorted(asset.value.path for asset in MiscAsset)
    on_disk = sorted(
        f"assets/{p.name}" for p in (_PLUGIN_DIR / "assets").iterdir()
    )
    assert declared == on_disk


def test_asset_decl_is_wired() -> None:
    """The misc plugin declares the enum, so boot registers/publishes them."""
    assert MiscPlugin.asset_decl is MiscAsset


async def test_random_footer_icon_resolves_published_emoji(
    seeded_bot, monkeypatch
) -> None:
    """A random member's published emoji becomes its CDN footer-icon URL."""
    await seeded_bot.db.execute(
        "UPDATE asset SET url = ? WHERE key = ?",
        "<:cirno_drunk:123456789012345678>",
        "MiscAsset.CIRNO_DRUNK",
    )
    monkeypatch.setattr(
        "plugins.misc.asset.random.choice",
        lambda _population: MiscAsset.CIRNO_DRUNK,
    )
    assert await random_footer_icon(seeded_bot) == (
        "https://cdn.discordapp.com/emojis/123456789012345678.png"
    )


async def test_random_footer_icon_none_while_unpublished(
    seeded_bot,
) -> None:
    """Unpublished (offline seeds have NULL urls) yields None — no icon."""
    assert await random_footer_icon(seeded_bot) is None


async def test_random_footer_icon_draws_from_the_full_set(
    seeded_bot, monkeypatch
) -> None:
    """Each call picks a fresh random member (mirrors tips.get_tip)."""
    populations: list[tuple[object, ...]] = []

    def _choice(population: list[MiscAsset]) -> MiscAsset:
        populations.append(tuple(population))
        return population[0]

    monkeypatch.setattr("plugins.misc.asset.random.choice", _choice)
    await random_footer_icon(seeded_bot)
    assert populations and set(populations[0]) == set(MiscAsset)
