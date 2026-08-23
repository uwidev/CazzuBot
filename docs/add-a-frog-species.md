# How do I... add a new frog species

A frog species ties together three things: a **capturable entity** (how it
spawns, what happens on catch), its **art asset**, and the **inventory
items** a caught frog becomes. All three are defined in code — there's no
species table in the database.

This example adds a **`BOG_FROG`** species. The existing leaf frog
(`plugins/frogs/`) is the reference.

## 1. Add the species key

`cazzubot/models.py` — the enum of valid species keys:

```python
class FrogItemKey(Enum):
    BASIC = "basic"
    BOG_FROG = "bog_frog"  # new
```

## 2. Add the art asset

Put the image in `plugins/frogs/assets/`, then declare it in
`plugins/frogs/assets.py` (see [add a new asset](add-an-asset.md)):

```python
class FrogAsset(Enum):
    FROG_BASIC = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog_basic.png"
    )
    ...
    BOG_FROG = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/bog_frog.png"
    )  # new
```

## 3. Define the species

`plugins/frogs/species.py` — add a `Species` to `SPECIES`:

```python
(
    Species(
        key=FrogItemKey.BOG_FROG,
        name="Bog Frog",
        rarity="uncommon",
        description="A frog from the bog.",
        spawn_weight=0.5,
        catch_effect=None,  # default catch: +1 to inventory
        art=FrogAsset.BOG_FROG,
    ),
)
```

- `spawn_weight` sets how likely it is to spawn relative to the others
  (weighted roll).
- `catch_effect` is optional; `None` uses the default catch (grant +1 to
  inventory). To give it a custom effect, see `plugins/frogs/effects.py`.

## 4. Add the inventory items

A caught frog becomes an item per species × state (normal/frozen), each with
its own consume exp. Add the items in `plugins/frogs/items.py`:

```python
class FrogItems(Enum):
    BASIC_NORMAL = _frog_item(
        "frog:basic:normal",
        "Basic Frog",
        "🐸",
        frog_exp(FrogItemKey.BASIC, FrogState.NORMAL),
    )
    ...
    BOG_NORMAL = _frog_item(
        "frog:bog_frog:normal",
        "Bog Frog",
        "🐸",
        frog_exp(FrogItemKey.BOG_FROG, FrogState.NORMAL),
    )
    BOG_FROZEN = _frog_item(
        "frog:bog_frog:frozen",
        "Bog Frog",
        "🐸",
        frog_exp(FrogItemKey.BOG_FROG, FrogState.FROZEN),
    )
```

`item_id` follows the shape `frog:<species_key>:<state>` — keep it in sync
with the key you added. Then register the per-state exp in `_SPECIES_EXP`:

```python
_SPECIES_EXP = {
    FrogItemKey.BASIC: {FrogState.NORMAL: 10, FrogState.FROZEN: 3},
    FrogItemKey.BOG_FROG: {
        FrogState.NORMAL: 30,
        FrogState.FROZEN: 9,
    },  # new
}
```

The minions, `/frog catalog`, and consumption all read from these two places.

## 5. Restart

```sh
uv run python main.py -d -s frogs
```

Or, if only the species/items/asset changed and the schema didn't, hot-reload
with `/plugin reload frogs`. On boot the species is registered and its art is
synced, so it appears in the spawn catalog.

## Notes

- The species key, art member, and item ids must all agree; a mismatch is a
  bug (the LSP catches a misspelled enum member, since everything is typed).
- Renaming an enum member is free. Changing a stored `item_id` is a migration
  — the ledger stores those exact strings.
