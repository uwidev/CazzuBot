"""In-place SQLite migrations for CazzuBot.

Each module here is one stateful (data) migration: the legacy shape is
detected by ``needs``, reported by ``plan``, rewritten by ``migrate`` (one
transaction, rollback on error), and optionally re-checked by ``verify`` —
see ``scripts/migrations/common.py`` for the contract. All five were
previously standalone one-off scripts (``scripts/migrate_poll_cid.py``,
``scripts/migrate_counter_events.py``, ``scripts/migrate_frog_species.py``,
``scripts/rename_asset_kind.py``, ``scripts/rename_frog_species_key.py``);
those files are now thin wrappers around this registry.

``MIGRATIONS`` is the authoritative run order for ``scripts/migrate.py``.
The ids are numbered for stable ordering; the migrations are independent
(shape-gated), so the numbering is purely conventional.
"""

from scripts.migrations import (
    asset_kind,
    counter_events,
    effect_contributions,
    frog_species,
    frog_species_key,
    poll_cid,
    status_contribution,
)
from scripts.migrations.common import Migration

MIGRATIONS = (
    poll_cid.MIGRATION,
    counter_events.MIGRATION,
    frog_species.MIGRATION,
    asset_kind.MIGRATION,
    frog_species_key.MIGRATION,
    effect_contributions.MIGRATION,
    status_contribution.MIGRATION,
)

__all__ = ["MIGRATIONS", "Migration"]
