"""Export renderer — offline unit tests."""

from __future__ import annotations

from cazzubot.roles.export import render_manifest
from cazzubot.roles.parser import VALID_FLAGS

SNAPSHOT = [
    {
        "position": 0,
        "id": "100",
        "name": "Owner",
        "color": None,
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 1,
        "id": "101",
        "name": "👀 | Mod Baka",
        "color": None,
        "hoisted": True,
        "mentionable": True,
        "managed": False,
        "permissions": [
            "view_channel",  # overlaps the member preset
            "manage_roles",
        ],
    },
    {
        "position": 2,
        "id": "102",
        "name": "✨ | Caz",
        "color": "#00a3ff",
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 3,
        "id": "103",
        "name": "Tatsumaki",
        "color": "#31d2f7",
        "hoisted": False,
        "mentionable": False,
        "managed": True,
        "permissions": ["manage_roles"],
    },
    {
        "position": 4,
        "id": "104",
        "name": "@everyone",
        "color": None,
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [
            "view_channel",
            "send_messages",
            "add_reactions",
            "read_message_history",
        ],
    },
]


def test_render_contains_cheatsheet_and_all_flags() -> None:
    text = render_manifest(SNAPSHOT)
    assert "── line format ──" in text
    assert "── all discord permissions ──" in text
    for flag in VALID_FLAGS:
        assert f" {flag}" in text or text.startswith(flag)


def test_render_derives_member_preset_from_everyone() -> None:
    text = render_manifest(SNAPSHOT)
    assert "[preset member]" in text
    assert (
        "view_channel" in text.split("[preset member]")[1].split("\n\n")[0]
    )


def test_render_groups_by_emoji_prefix_in_order() -> None:
    # no marker roles in the snapshot → no headers, pure positional order
    text = render_manifest(SNAPSHOT)
    assert "[👀]" not in text
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    names = [ln.split(" : ")[0] for ln in lines]
    assert names.index("Owner") < names.index("👀 | Mod Baka")
    assert names.index("✨ | Caz") < names.index("Tatsumaki")


def test_render_markers_as_headers() -> None:
    snapshot = [
        {**dict(r), "name": "[Vanity]"} if r["name"] == "Tatsumaki" else r
        for r in SNAPSHOT
    ]
    text = render_manifest(snapshot)
    # the marker's name IS the header, and it appears in positional order
    assert "[Vanity]" in text
    assert text.index("Owner") < text.index("✨ | Caz")
    assert text.index("✨ | Caz") < text.index("[Vanity]")


def test_render_managed_roles_name_only() -> None:
    text = render_manifest(SNAPSHOT)
    assert "Tatsumaki\n" in text  # no tokens attached


def test_render_perm_tokens_via_preset_match() -> None:
    text = render_manifest(SNAPSHOT)
    # Mod Baka's perms overlap the member preset → preset + diff form
    line = next(
        ln for ln in text.splitlines() if ln.startswith("👀 | Mod Baka")
    )
    assert "preset:member" in line
    assert "+manage_roles" in line
    assert "-send_messages" in line


def test_render_excludes_everyone_and_modeline_last() -> None:
    text = render_manifest(SNAPSHOT)
    # @everyone never appears as a role line (footer mention is fine)
    assert not any(line == "@everyone" for line in text.splitlines())
    assert text.strip().endswith("# vim: ft=txt :")


def test_render_source_note() -> None:
    text = render_manifest(SNAPSHOT, source="data/roles_export.json")
    assert "# Generated from data/roles_export.json" in text


def test_render_exported_stamp() -> None:
    text = render_manifest(SNAPSHOT, exported="2026-08-07 18:53:12 UTC")
    assert "# Exported 2026-08-07 18:53:12 UTC" in text


def test_render_no_presets_falls_back_to_plus_flags() -> None:
    text = render_manifest(SNAPSHOT, presets={})
    line = next(
        ln for ln in text.splitlines() if ln.startswith("👀 | Mod Baka")
    )
    assert "+manage_roles" in line
    assert "preset:" not in line
