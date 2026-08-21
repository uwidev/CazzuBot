# How do I... add a new asset

An asset is an image (or emoji) a plugin shows to users — species art, a
banner, an icon. Assets are **declared in code** as an enum; the file lives
inside the plugin's folder. At boot the bot hashes each file, registers an
entry, and publishes it to a shared asset guild (a CDN URL for media, a
`<:name:id>` emoji for emoji). Code references the asset **by enum member
only** — never by path or URL.

This example adds **`badge_common.png`** to a `badges` plugin.

## 1. Put the file in the plugin folder

```
plugins/badges/assets/badge_common.png
```

The path is relative to the plugin folder.

## 2. Declare it in the plugin's asset enum

`plugins/badges/assets.py`:

```python
from enum import Enum

from cazzubot.assets import AssetKind, AssetSpec


class BadgeAsset(Enum):
    COMMON = AssetSpec(kind=AssetKind.EMOJI, path="assets/badge_common.png")
    BANNER = AssetSpec(kind=AssetKind.SPECIES, path="assets/banner.png")
```

Choose the kind:

- `AssetKind.EMOJI` — created as a custom emoji in the asset guild,
  referenced as `<:name:id>`. Image must be ≤ 256 KB.
- `AssetKind.SPECIES` — CDN-published into the asset channel, referenced by
  URL. Good for larger images like banners.

## 3. Wire it into the plugin

In the plugin class (`plugins/badges/__init__.py`):

```python
from .assets import BadgeAsset

class BadgesPlugin(Plugin):
    name = "badges"
    ...
    asset_decl = BadgeAsset
```

## 4. Restart

```sh
uv run python main.py -d -s badges
```

On boot the bot registers the asset and publishes it. A missing file is a
boot error; a changed file re-publishes. You can also hot-reload with
`/plugin reload badges`.

## 5. Use it

`bot.assets.get(member)` returns the published reference (URL or emoji), or
`None` if it isn't published yet:

```python
from .assets import BadgeAsset

ref = await bot.assets.get(BadgeAsset.COMMON)
```

## Notes

- The registry key is **derived** from the enum member (`BadgeAsset.COMMON`),
  never hand-written. Renaming the member is fine.
- The file on disk is the source of truth — edit the image and redeploy, and
  boot re-syncs it.
- If the asset guild/channel isn't configured (see `.env`:
  `ASSET_GUILD_ID` / `ASSET_CHANNEL_ID`), the bot boots but skips the sync
  with a warning, and `get()` returns `None`.
