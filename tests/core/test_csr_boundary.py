"""CSR boundary enforcement — service/repository modules never import discord.

Service modules (``logic.py``/``factory.py``) and repository modules
(``db.py``) take ``db``/``settings`` + plain values (+ injected ``now``);
importing the stateful ``discord`` package couples them to the
ConnectionState-requiring layer and forces fakes into their unit tests.
Validation failures raise ``cazzubot.errors.UserInputError`` (never
``commands.BadArgument``); the command edge translates them back.

One permanent carve-out: ``plugins/frogs/factory.py`` stays
controller-shaped by design (the spawn handler and capture view are
scheduling + discord side effects — see docs/DONE.md). Everything else
under ``plugins`` must NOT import discord — and since the hikari port, the
test infrastructure (``tests/fakes.py``/``conftest.py``) must not either:
the suite's fakes are the contract for the hikari surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

SERVICE_FILENAMES = ("logic.py", "factory.py", "db.py")

# Permanent controller-shaped carve-out (documented in docs/DONE.md).
_ALLOWLIST = {
    "plugins.frogs.factory",  # spawn handler + capture view (controller)
}

_TEST_DIR = "tests"


def _imports_discord(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "discord"
                or alias.name.startswith("discord.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("discord"):
                return True
    return False


def _service_modules() -> list[Path]:
    return sorted(
        p
        for p in Path("plugins").rglob("*.py")
        if p.name in SERVICE_FILENAMES
    )


def _test_modules() -> list[Path]:
    return sorted(
        p
        for p in Path(_TEST_DIR).rglob("*.py")
        if p.name in ("fakes.py", "conftest.py")
    )


def test_service_modules_do_not_import_discord() -> None:
    offenders = [
        path
        for path in _service_modules()
        if ".".join(path.with_suffix("").parts) not in _ALLOWLIST
        and _imports_discord(path)
    ]
    assert offenders == [], (
        "service modules must not import discord: "
        + ", ".join(str(p) for p in offenders)
    )


def test_fakes_do_not_import_discord() -> None:
    offenders = [
        path for path in _test_modules() if _imports_discord(path)
    ]
    assert offenders == [], (
        "test infrastructure must not import discord: "
        + ", ".join(str(p) for p in offenders)
    )


def test_core_modules_do_not_import_discord() -> None:
    """cazzubot core is discord-free since the hikari port (CLI included)."""
    offenders = [
        path
        for path in Path("cazzubot").rglob("*.py")
        if _imports_discord(path)
    ]
    assert offenders == [], (
        "core modules must not import discord: "
        + ", ".join(str(p) for p in offenders)
    )
