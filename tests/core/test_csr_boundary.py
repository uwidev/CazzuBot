"""CSR boundary enforcement — service/repository modules never import discord.

Service modules (``logic.py``/``factory.py``) and repository modules
(``db.py``) take ``db``/``settings`` + plain values (+ injected ``now``);
importing the stateful ``discord`` package couples them to the
ConnectionState-requiring layer and forces fakes into their unit tests.

One carve-out: ``from discord.ext import commands`` is allowed in service
modules for the plain ``commands.BadArgument`` exception (validation errors)
— it holds no ConnectionState. Anything else under ``discord`` is flagged.

Still-pure-pending (tracked in docs/BACKLOG.md #7): the presentation modules
below remain coupled to the core package until their extraction step. New
service modules must NOT join this allowlist.
"""

from __future__ import annotations

import ast
from pathlib import Path

SERVICE_FILENAMES = ("logic.py", "factory.py", "db.py")

# Tracked remainder of the #7 extraction order.
_ALLOWLIST = {
    "plugins.levels.logic",  # handle_level_up presentation
    "plugins.ranks.logic",  # handle_ranks presentation
    "plugins.frogs.factory",  # spawn handler + capture view (controller)
}


def _service_modules() -> list[Path]:
    return sorted(
        p
        for p in Path("plugins").rglob("*.py")
        if p.name in SERVICE_FILENAMES
    )


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
            if node.module == "discord":
                return True
            # discord.ext.commands only: the plain BadArgument exception
            if (node.module or "").startswith("discord.") and (
                node.module != "discord.ext"
            ):
                return True
    return False


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
