"""Snapshot domain: fetch the live guild's role layout into a JSON file.

The snapshot is the plain-data source for the offline ``manifest render``
verb and for ``roles restore`` backups.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import hikari

from cazzubot.cli.core import Command, Domain, require_guild
from cazzubot.config import Config
from cazzubot.roles import executor

SNAPSHOT_PATH = Path("data/roles_export.json")


async def cmd_fetch(
    client: hikari.api.RESTClient,
    config: Config,
    _args: argparse.Namespace,
) -> int:
    """Snapshot the guild's roles to ``data/roles_export.json``."""
    guild = await require_guild(client, config)
    if guild is None:
        return 1
    data = await executor.snapshot_guild(client, config.guild_id)
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"{guild.name} — {len(data)} roles -> {SNAPSHOT_PATH}")
    for role in data:
        color = role["color"] or "none"
        flags = [
            f for f in ("hoisted", "mentionable", "managed") if role[f]
        ]
        perms = ",".join(role["permissions"]) or "-"
        print(
            f"{role['position']:>3}  {role['name']}  [{color}] {','.join(flags)}"
        )
        print(f"        id={role['id']}  perms: {perms}")
    return 0


domain = Domain(
    name="snapshot",
    help="fetch the live guild state into data/roles_export.json",
    commands={
        "fetch": Command(
            cmd_fetch,
            live=True,
            help="snapshot roles to data/roles_export.json",
        ),
    },
)
