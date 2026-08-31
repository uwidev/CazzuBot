How do I… add a new frog species
================================

A frog species ties together three things: a **capturable entity** (how it
spawns, what happens on catch), its **art asset**, and the **inventory
items** a caught frog becomes. All three are defined in code — there's no
species table in the database.

This example adds a **`BOG_FROG`** species. The existing leaf frogs
(`plugins/frogs/`) are the reference.


1. Add the species key
----------------------

`cazzubot/models.py` — the enum of valid species keys:

~~~~ python
class FrogItemKey(Enum):
    BASIC = "basic"
    BOG_FROG = "bog_frog"  # new
~~~~


2. Add the art asset
--------------------

Put the image in `plugins/frogs/assets/`, then declare it in
`plugins/frogs/assets.py` (see [add a new asset](add-an-asset.md)):

~~~~ python
class FrogAsset(Enum):
    FROG_BASIC = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog_basic.png"
    )
    ...
    BOG_FROG = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/bog_frog.png"
    )  # new
~~~~


3. Define the species — compose its behavior
--------------------------------------------

`plugins/frogs/species.py` — add a `Species` to `SPECIES`. A species is a
**mob**: its `catch` and `spawn` fields are code (callables), so the
species composes its own behavior:

~~~~ python
Species(
    key=FrogItemKey.BOG_FROG,
    name="Bog Frog",
    rarity="uncommon",
    description="A frog from the bog.",
    spawn_weight=0.5,
    catch=grant_catch,  # +1 to inventory + the capture embed
    spawn=None,         # the normal catchable path
    art=FrogAsset.BOG_FROG,
)
~~~~

 -  `spawn_weight` sets how likely it is to spawn relative to the others
    (weighted roll).
 -  `catch` is the capture hook — **code, not data**. `None` means *nothing
    happens* on capture (the item is only granted if a catch behavior does
    it); the catchable frogs compose the shared `grant_catch` helper
    (`plugins/frogs/behaviors.py`). A species that wants a custom catch
    writes its own async behavior beside itself — there's no registry or
    payload shape to declare.
 -  `spawn` is the spawn hook — `None` for the normal catchable frog; a
    spawn-owning species (like Cluster's `ClusterBurst`) replaces the
    catchable frog entirely and is uncatchable by design.


4. Add the inventory items
--------------------------

A caught frog becomes an item per species × state (normal/frozen), each with
its own consume exp. Add the items in `plugins/frogs/items.py` — each is a
bare `Item` literal (no builder):

~~~~ python
class FrogItems(Enum):
    BASIC = Item(
        item_id="frog:basic:normal",
        display_name="Basic Frog",
        icon="🐸",
        description="The most normalest frog of them all.",
        icon_asset=FrogAsset.FROG_BASIC,
        consume=_consume_basic_normal,
        fields=(_consumption_field(FrogItemKey.BASIC, FrogState.NORMAL),),
    )
    ...
    BOG_NORMAL = Item(
        item_id="frog:bog_frog:normal",
        display_name="Bog Frog",
        icon="🐸",
        description="A frog from the bog.",
        icon_asset=FrogAsset.BOG_FROG,
        consume=_consume_bog_normal,  # a _consume_item glue for its id
        fields=(_consumption_field(FrogItemKey.BOG_FROG, FrogState.NORMAL),),
    )
    BOG_FROZEN = Item(  # ... "frog:bog_frog:frozen", FROZEN state
        ...
    )
~~~~

`item_id` follows the shape `frog:<species_key>:<state>` — keep it in sync
with the key you added. The per-item consume glue delegates to the shared
`_consume_item` with its own id; the glue grants exp from the `frog_exp`
oracle and applies the item's declared statuses. Then register the per-state
exp in `_SPECIES_EXP`:

~~~~ python
_SPECIES_EXP = {
    FrogItemKey.BASIC: {FrogState.NORMAL: 10, FrogState.FROZEN: 3},
    FrogItemKey.BOG_FROG: {
        FrogState.NORMAL: 30,
        FrogState.FROZEN: 9,
    },  # new
}
~~~~

The minions, `/frog catalog`, and consumption all read from these two places.


5. Give it a consume effect (optional)
--------------------------------------

If the item should trigger a status on consume (a reaction chance, a role
grant), declare a **status class** in `plugins/frogs/statuses.py` and name it
in `_ITEM_STATUSES` — the item's composition is the classes it lists:

~~~~ python
@dataclass(frozen=True, slots=True, kw_only=True)
class BogStatus(Status):
    """Example — the class owns every value of the effect."""

    chance: float

    @override
    def describe(self) -> str:
        return f"Grants a **{self.chance:.0%}** chance to …"

BOG_STATUS = BogStatus(
    key="frog:blessing:bog", name="…", seam=FrogSeam.FROG_REACTION, …
)
~~~~

~~~~ python
_ITEM_STATUSES["frog:bog_frog:normal"] = (BOG_STATUS,)
~~~~

The status class owns its values (chance, duration, policy, priority); the
store records only provenance, and the consuming feature's pull reads the
values off the class — single source of truth, no payload drift.


6. Restart
----------

~~~~ sh
uv run python main.py -d -s frogs
~~~~

Or, if only the species/items/asset changed and the schema didn't, hot-reload
with `/plugin reload frogs`. On boot the species is registered and its art is
synced, so it appears in the spawn catalog.


Notes
-----

 -  The species key, art member, and item ids must all agree; a mismatch is a
    bug (the LSP catches a misspelled enum member, since everything is typed).
 -  Renaming an enum member is free. Changing a stored `item_id` is a migration
    — the ledger stores those exact strings.
