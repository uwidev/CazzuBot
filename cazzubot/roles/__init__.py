"""Declarative role management.

The role manifest is a line-oriented text file (``roles.manifest``) that
declares the guild's roles: ordered groups, one role per line, with color /
hoist / mentionable / icon / permission tokens. The engine diffs it against
the live guild and applies the plan via the admin CLI (``uv run cazzubot-cli
roles …``) or the boot-time drift check plugin.

See docs/PLUGINS.md → roles for the format reference.
"""

from cazzubot.roles.export import render_manifest
from cazzubot.roles.parser import (
    GroupSpec,
    Issue,
    Manifest,
    ManifestError,
    NAMED_COLORS,
    PresetSpec,
    RoleSpec,
    VALID_FLAGS,
    parse,
    rewrite_renames,
)
from cazzubot.roles.plan import (
    CreateOp,
    DeleteOp,
    Plan,
    RenameOp,
    UpdateOp,
    build_plan,
)

__all__ = [
    "CreateOp",
    "DeleteOp",
    "GroupSpec",
    "Issue",
    "Manifest",
    "ManifestError",
    "NAMED_COLORS",
    "Plan",
    "PresetSpec",
    "RenameOp",
    "RoleSpec",
    "UpdateOp",
    "VALID_FLAGS",
    "build_plan",
    "parse",
    "render_manifest",
    "rewrite_renames",
]
