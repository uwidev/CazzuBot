"""DB boundary enforcement — row fetches become models at the module edge.

Repository modules (``plugins/*/db.py``) and the core table owners
(``scheduler``/``settings``/``member_effects``/``assets``) must never expose a
raw ``aiosqlite.Row`` (or untyped ``Any`` JSON) as a public return type: the
caller gets a dataclass (``fetch_model``/``fetch_models``), or a precisely
typed tuple/scalar for projections (``rank_rows`` results, ``fetchval``
counts). Coercion from stored TEXT/INTEGER to field types lives in
``row_to``/``rows_to`` — see ``tests/core/test_db.py``.

One carve-out: ``cazzubot/settings.py`` is an intentionally untyped JSON
key-value store (``Any`` is the honest type there — see
``docs/PLAN_DB_MODELS.md`` D3).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_TABLE_OWNERS = (
    "cazzubot/scheduler.py",
    "cazzubot/settings.py",
    "cazzubot/member_effects.py",
    "cazzubot/assets.py",
)

# settings.get returns Any by design: an untyped JSON key-value store does not
# commit to a value type (docs/PLAN_DB_MODELS.md D3).
_ANY_ALLOWED = {
    ("cazzubot/settings.py", "get"),
}


def _target_modules() -> list[Path]:
    """The repository modules the boundary rule applies to."""
    db_modules = sorted(Path("plugins").rglob("db.py"))
    return db_modules + [Path(p) for p in _TABLE_OWNERS]


def _forbidden(annotation_text: str) -> bool:
    """Raw rows and untyped JSON dicts are forbidden return shapes."""
    if re.search(r"\bRow\b", annotation_text):
        return True  # aiosqlite.Row / Row | None leaking out of the module
    if annotation_text == "Any":
        return True
    return False


def test_no_raw_rows_cross_db_module_boundary() -> None:
    """Every public db-module function returns a model or a typed shape.

    ``Row``/``Any`` in a return annotation means a dynamic sqlite row (or an
    untyped JSON value) is being handed to callers — the exact friction the
    model boundary exists to remove.
    """
    failures: list[str] = []
    for module in _target_modules():
        tree = ast.parse(module.read_text())
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            if node.name.startswith("_"):
                continue
            if (str(module), node.name) in _ANY_ALLOWED:
                continue
            if node.returns is None:
                failures.append(
                    f"{module}:{node.lineno} {node.name}: "
                    + "missing return annotation"
                )
                continue
            text = ast.unparse(node.returns)
            if _forbidden(text):
                failures.append(
                    f"{module}:{node.lineno} {node.name}: returns {text!r}"
                )
    assert not failures, (
        "DB module functions must return models or typed shapes, not raw "
        "rows/Any:\n" + "\n".join(failures)
    )
