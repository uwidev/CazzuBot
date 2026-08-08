"""Declarative channel management.

The channel manifest (``channels.manifest``) is a line-oriented text file
that declares the guild's channels: ``[Category]`` headers map to Discord's
native category grouping, one channel per line with Overview-field tokens
(name / type / category / position / slowmode / nsfw / bitrate / user
limit / region / video quality — everything except the topic), plus
``OLD->NEW`` rename lines. The engine diffs it against the live guild and
applies the plan via the admin CLI (``uv run cazzubot-cli channels …``) or
the boot-time drift check plugin.

See docs/PLUGINS.md → channels for the format reference.
"""

from cazzubot.channels.export import render_manifest
from cazzubot.channels.parser import (
    ChannelSpec,
    GroupSpec,
    Issue,
    Manifest,
    ManifestError,
    parse,
    rewrite_renames,
)
from cazzubot.channels.plan import (
    CreateOp,
    DeleteOp,
    Plan,
    RenameOp,
    UpdateOp,
    build_plan,
)

__all__ = [
    "ChannelSpec",
    "CreateOp",
    "DeleteOp",
    "GroupSpec",
    "Issue",
    "Manifest",
    "ManifestError",
    "Plan",
    "RenameOp",
    "UpdateOp",
    "build_plan",
    "parse",
    "render_manifest",
    "rewrite_renames",
]
