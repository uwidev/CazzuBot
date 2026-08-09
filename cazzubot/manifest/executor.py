"""Executor plumbing shared by the roles/channels apply engines.

Both executors apply a plan the same way (renames → creates → updates →
deletes → reorder, verifying every op against a fresh API view), but the
per-op bodies are domain-specific and stay in the domains. What is
identical — the result type, snapshot JSON I/O, backup naming and the
reorder retry bound — lives here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pendulum

from cazzubot.manifest.plan import RenameOp

REORDER_ATTEMPTS = 5

# how long to let the gateway settle between reorder attempts
REORDER_SETTLE = 0.6


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Outcome of an apply: errors plus the renames that actually ran."""

    errors: list[str]
    applied_renames: list[RenameOp]


def save_snapshot(path: Path, items: list[Any]) -> None:
    """Write a snapshot list to JSON (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_snapshot(path: Path) -> list[Any]:
    """Read a snapshot list written by :func:`save_snapshot`."""
    return json.loads(path.read_text(encoding="utf-8"))


def backup_path(base: Path, prefix: str) -> Path:
    """``<base>/<prefix>-YYYYMMDD-HHMMSS.json`` in UTC."""
    stamp = pendulum.now("UTC").format("YYYYMMDD-HHmmss")
    return base / f"{prefix}-{stamp}.json"
