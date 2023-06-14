"""Serves as a handler for registering per-cog settings into the database.

Values should be already converted to appropriate types.
"""
from collections.abc import Mapping

from src.db_templates import defaults


def register_settings(settings: Mapping):
    """Add the collection of settings onto the global defaults."""
    defaults.update(settings)
