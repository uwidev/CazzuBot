How do I… add a schema
======================

Each plugin owns its tables. Put the DDL in a `db.py` inside the plugin
folder and point the plugin at it with `schema`.


1. Write the schema
-------------------

`plugins/<name>/db.py`:

~~~~ python
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS badges (
        id  INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_badges_uid ON badges (uid)",
]
~~~~

Wire it up in `plugins/<name>/__init__.py`:

~~~~ python
from . import db


class BadgesPlugin(Plugin):
    name = "badges"
    schema = db.SCHEMA
~~~~


2. Rules
--------

 -  **Idempotent** — every statement uses `IF NOT EXISTS`. The boot guard
    checks the live DB against the Python DDL and aborts on drift, so the
    statements run once and must not fight each other on reload.
 -  **Enums → TEXT** — store enums as their `.value` string; a row model
    reads them back as the enum.
 -  **Timestamps → ISO-8601 UTC** — write with
    `pendulum.now("UTC").to_iso8601_string()` / `.isoformat()`; a row model
    reads them back as `pendulum.DateTime`.
 -  **Dict/list → JSON text** — use `bot.db.dump_json` / `load_json`; a row
    model reads them back as `dict`/`list`.
 -  **Row fetches → typed models** — each query that returns rows maps into a
    dataclass with `fetch_model`/`fetch_models`: `row_to`/`rows_to` coerce the
    stored values into the field's declared type (DateTime, enums, JSON
    dicts/lists, `bool`, `X | None`). One dataclass per row shape, reused
    across queries and projections. Raw `aiosqlite.Row`/`Any` never crosses a
    db module's public API — enforced by `tests/core/test_db_boundary.py`
    (`cazzubot/settings.py` is the untyped-JSON carve-out). Projections
    (aggregates, ranked rows) stay precise tuples/scalars instead.
 -  **One guild only** — no `gid` columns.
 -  **Writes idempotent** — `INSERT OR IGNORE` / `INSERT OR REPLACE`.

See `plugins/experience/db.py` (`member_exp`, `member_exp_log`) for a small
real example, `plugins/counter/db.py` / `plugins/mod/db.py` for the
schema + repository-layer + row-model pattern, and `cazzubot/scheduler.py`
for a core table owner (`Task`).


3. Restart to apply
-------------------

Schema changes need a **restart** — a hot `/plugin reload` does not rebuild
tables. Run sandboxed to check just your plugin:

~~~~ sh
uv run python main.py -d -s badges
~~~~
