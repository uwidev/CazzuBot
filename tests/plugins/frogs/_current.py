"""Reload-safe accessors for the frog status/reaction/item modules.

The plugin-reload tests (``tests/core/test_boot.py``) purge and re-import
``plugins.frogs.*`` mid-suite, which replaces the module-global status
class instances in the ``cazzubot.statuses`` registry. A test module that
imports those instances at collection time would hold **stale** references
that no longer match the registry (``isinstance``/``is`` checks fail).
Resolve the modules at call time so the references always match the
current registry — the statuses are keyed by stable strings either way.
"""

from __future__ import annotations


def statuses():
    """The current ``plugins.frogs.statuses`` module (post-reload safe)."""
    import plugins.frogs.statuses as module

    return module


def reactions():
    """The current ``plugins.frogs.reactions`` module (post-reload safe)."""
    import plugins.frogs.reactions as module

    return module


def items():
    """The current ``plugins.frogs.items`` module (post-reload safe)."""
    import plugins.frogs.items as module

    return module


def events():
    """The current ``plugins.frogs.events`` module (post-reload safe)."""
    import plugins.frogs.events as module

    return module
