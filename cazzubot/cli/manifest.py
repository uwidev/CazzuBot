"""Manifest domain: offline manifest file work (no discord connection).

``render`` converts a fetched snapshot into a manifest; ``lint`` parses a
manifest and reports problems with exit code for hooks. Both run without
ever touching the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cazzubot.cli.core import (
    Command,
    Domain,
    EXPORT_PRESETS,
    export_stamp,
)
from cazzubot.cli.snapshot import SNAPSHOT_PATH
from cazzubot.manifest.cli import add_file_args
from cazzubot.roles.export import render_manifest
from cazzubot.roles.parser import ManifestError, parse


async def cmd_render(args: argparse.Namespace) -> int:
    """Offline: snapshot JSON -> manifest at --file (default roles.manifest)."""
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except OSError as err:
        print(
            f"error: cannot read {SNAPSHOT_PATH}: {err}", file=sys.stderr
        )
        return 1
    text = render_manifest(
        data,
        presets=EXPORT_PRESETS,
        source=f"{SNAPSHOT_PATH} by cazzubot.cli manifest render",
        exported=export_stamp(),
    )
    args.file.write_text(text, encoding="utf-8")
    print(f"wrote {args.file} ({text.count(chr(10))} lines)")
    return 0


async def cmd_lint(args: argparse.Namespace) -> int:
    """Offline: parse the manifest; exit 1 on any problem."""
    try:
        text = args.file.read_text(encoding="utf-8")
    except OSError as err:
        print(f"error: cannot read {args.file}: {err}", file=sys.stderr)
        return 1
    try:
        manifest = parse(text)
    except ManifestError as err:
        for issue in err.issues:
            print(f"{args.file}:{issue}", file=sys.stderr)
        return 1
    groups = len(manifest.groups)
    roles = len(manifest.role_names())
    print(f"ok — {groups} group(s), {roles} role(s)")
    return 0


domain = Domain(
    name="manifest",
    help="offline manifest file work (render/lint, no discord connection)",
    common_args=(add_file_args(Path("roles.manifest")),),
    commands={
        "render": Command(
            cmd_render,
            live=False,
            help="render roles.manifest from data/roles_export.json",
        ),
        "lint": Command(
            cmd_lint,
            live=False,
            help="parse the manifest and report problems",
        ),
    },
)
