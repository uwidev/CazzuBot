"""Declarative role management.

The role manifest is a line-oriented text file (``roles.manifest``) that
declares the guild's roles: ordered groups, one role per line, with color /
hoist / mentionable / icon / permission tokens. The engine diffs it against
the live guild and applies the plan via the admin CLI (``uv run cazzubot-cli
roles …``) or the boot-time drift check plugin.

See docs/PLUGINS.md → roles for the format reference.
"""
