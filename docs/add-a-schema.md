# How do I... add a schema

Each plugin owns its tables. Put the DDL in a `db.py` inside the plugin
folder and point the plugin at it with `schema`.

## 1. Write the schema

`plugins/<name>/db.py`:

```python
SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS badges (
        id  INTEGER PRIMARY KEY AUTOINCREMENT,
        uid INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_badges_uid ON badges (uid)",
]
```

Wire it up in `plugins/<name>/__init__.py`:

```python
from . import db


class BadgesPlugin(Plugin):
    name = "badges"
    schema = db.SCHEMA
```

## 2. Rules

- **Idempotent** — every statement uses `IF NOT EXISTS`. The boot guard
  checks the live DB against the Python DDL and aborts on drift, so the
  statements run once and must not fight each other on reload.
- **Enums → TEXT** — store enums as their `.value` string.
- **Timestamps → ISO-8601 UTC** — `pendulum.now("UTC").to_iso8601_string()`.
- **Dict/list → JSON text** — use `bot.db.dump_json` / `load_json`.
- **One guild only** — no `gid` columns.
- **Writes idempotent** — `INSERT OR IGNORE` / `INSERT OR REPLACE`.

See `plugins/experience/db.py` (`member_exp`, `member_exp_log`) for a small
real example, and `plugins/counter/db.py` for the schema + repository-layer
pattern in one file.

## 3. Restart to apply

Schema changes need a **restart** — a hot `/plugin reload` does not rebuild
tables. Run sandboxed to check just your plugin:

```sh
uv run python main.py -d -s badges
```
