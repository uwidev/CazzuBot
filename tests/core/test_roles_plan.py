"""Plan engine — offline unit tests (no discord connection)."""

from __future__ import annotations

from typing import Any, cast

from cazzubot.roles.parser import parse
from cazzubot.roles.plan import build_plan
from cazzubot.roles.snapshot import RoleSnapshot

SNAPSHOT: list[RoleSnapshot] = [
    # top-down sidebar order; position 0 = highest. [X] entries are the
    # group-marker roles the manifest [X] headers map to.
    {
        "position": 0,
        "id": "0",
        "name": "[Staff]",
        "color": None,
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 1,
        "id": "1",
        "name": "Owner",
        "color": None,
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 2,
        "id": "2",
        "name": "👀 | Mod Baka",
        "color": None,
        "hoisted": True,
        "mentionable": True,
        "managed": False,
        "permissions": ["manage_roles", "kick_members"],
    },
    {
        "position": 3,
        "id": "3",
        "name": "[✨]",
        "color": None,
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 4,
        "id": "4",
        "name": "✨ | Caz",
        "color": "#00a3ff",
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 5,
        "id": "5",
        "name": "[🤖 Bots]",
        "color": None,
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 6,
        "id": "6",
        "name": "Tatsumaki",
        "color": "#31d2f7",
        "hoisted": False,
        "mentionable": False,
        "managed": True,
        "permissions": ["manage_roles"],
    },
    {
        "position": 7,
        "id": "7",
        "name": "[Misc]",
        "color": None,
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 8,
        "id": "8",
        "name": "Muted",
        "color": "#af40ff",
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 9,
        "id": "9",
        "name": "🎨 | Blue",
        "color": "#4f8cc9",
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
    {
        "position": 10,
        "id": "10",
        "name": "@everyone",
        "color": None,
        "hoisted": False,
        "mentionable": False,
        "managed": False,
        "permissions": [],
    },
]


def mutated(name: str, **fields: Any) -> list[RoleSnapshot]:
    """SNAPSHOT with one role's fields replaced by ``fields``."""
    return [
        cast(Any, {**dict(r), **fields}) if r["name"] == name else r
        for r in SNAPSHOT
    ]


IDENTICAL = """\
[preset mod]
manage_roles kick_members

[Staff]
Owner
👀 | Mod Baka : hoist mentionable preset:mod

[✨]
✨ | Caz : #00a3ff

[🤖 Bots]
Tatsumaki

[Misc]
Muted : #af40ff
🎨 | Blue : #4f8cc9
"""

# like IDENTICAL but without the Muted role — Muted is an unlisted stray
WITHOUT_MUTED = IDENTICAL.replace("Muted : #af40ff\n", "")

BOT_TOP = 2  # the bot's highest role is 👀 | Mod Baka (position 2)


def test_clean_manifest() -> None:
    plan = build_plan(parse(IDENTICAL), SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan.is_clean()
    assert (
        plan.summary()
        == "create 0 · update 0 · rename 0 · order ok · delete 0 · 2 out of reach"
    )
    assert plan.out_of_reach == ["[Staff]", "Owner"]


def test_missing_marker_is_a_create() -> None:
    manifest = parse("[New Group]\n✨ | Caz : #00a3ff\n")
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert [op.spec.name for op in plan.creates] == ["[New Group]"]


def test_create_and_update() -> None:
    manifest = parse(
        """\
[Staff]
Owner
👀 | Mod Baka : mentionable  # hoist dropped → update

[✨]
✨ | Caz : #00a3ff
Brand New : #ff0000
"""
    )
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert [op.spec.name for op in plan.creates] == ["Brand New"]
    assert [op.name for op in plan.updates] == ["👀 | Mod Baka"]
    assert plan.updates[0].changes["hoist"] == (True, False)


def test_update_color_normalized() -> None:
    manifest = parse("[✨]\n✨ | Caz : #00A3FF\n")  # uppercase hex
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan.updates == []  # same color, case-insensitive


def test_deletes_require_flag() -> None:
    plan = build_plan(
        parse(WITHOUT_MUTED), SNAPSHOT, bot_top_role_id=BOT_TOP
    )
    assert plan.deletes == []
    assert plan.strays == ["Muted"]
    plan2 = build_plan(
        parse(WITHOUT_MUTED),
        SNAPSHOT,
        bot_top_role_id=BOT_TOP,
        delete=True,
    )
    assert [op.name for op in plan2.deletes] == ["Muted"]


def test_managed_roles_never_deleted_or_updated() -> None:
    manifest = parse(
        "[🤖 Bots]\nTatsumaki : #000000\n"  # attr change on managed role
    )
    plan = build_plan(
        manifest, SNAPSHOT, bot_top_role_id=BOT_TOP, delete=True
    )
    assert plan.updates == []
    assert "Tatsumaki" in plan.managed_skipped
    assert "Tatsumaki" not in [d.name for d in plan.deletes]


def test_out_of_reach_reorder_blocked_only_when_moving() -> None:
    # Owner keeps its spot → not blocked
    plan = build_plan(parse(IDENTICAL), SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert not plan.reorder_blocked

    # Owner (or the bot's own role next to it) would move → blocked
    manifest = parse(
        "[Staff]\n[✨]\n✨ | Caz : #00a3ff\nOwner : mentionable\n"
    )
    plan2 = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan2.reorder_blocked
    assert "Owner" in plan2.moving_unmovable()


def test_reachable_reorder_not_blocked_by_unmoved_out_of_reach() -> None:
    # swapping two reachable roles (Muted and 🎨 | Blue) inside [Misc] is
    # fine even though [Staff]/Owner/Mod Baka sit above it
    manifest = parse(
        """\
[preset mod]
manage_roles kick_members

[Staff]
Owner
👀 | Mod Baka : hoist mentionable preset:mod

[✨]
✨ | Caz : #00a3ff

[🤖 Bots]
Tatsumaki

[Misc]
🎨 | Blue : #4f8cc9
Muted : #af40ff
"""
    )
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan.needs_reorder
    assert not plan.reorder_blocked


def test_reorder_blocked_when_bot_top_role_moves() -> None:
    # the bot's own highest role (Mod Baka) can't be reordered either
    manifest = parse(
        """\
[Staff]
Owner
✨ | Caz : #00a3ff
👀 | Mod Baka : hoist mentionable
"""
    )
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan.reorder_blocked
    assert plan.moving_unmovable() == ["👀 | Mod Baka"]


def test_reorder_blocked_when_role_crosses_above_bot() -> None:
    # a role below the bot (Muted) targeted above the bot's top role (Mod
    # Baka) is blocked — the bot can't move roles across its own top role
    manifest = parse(
        """\
[Staff]
Muted : #af40ff
Owner
👀 | Mod Baka : hoist mentionable
"""
    )
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan.reorder_blocked
    assert "Muted" in plan.moving_unmovable()


def test_bot_tagged_managed_role_is_movable() -> None:
    # a bot/integration role (tags=["bot"]) CAN be reordered — it is not
    # unmovable, unlike a boost role
    snapshot = mutated("Tatsumaki", tags=["bot"])
    plan = build_plan(parse(IDENTICAL), snapshot, bot_top_role_id=BOT_TOP)
    assert "Tatsumaki" not in plan.unmovable


def test_boost_tagged_role_is_movable() -> None:
    # boost roles ARE movable via the API (verified on production) — only
    # positions at/above the bot's top role are unmovable
    snapshot = mutated("🎨 | Blue", tags=["premium_subscriber"])
    plan = build_plan(parse(IDENTICAL), snapshot, bot_top_role_id=BOT_TOP)
    assert "🎨 | Blue" not in plan.unmovable


def test_no_bot_top_role_means_everything_reachable() -> None:
    plan = build_plan(parse(IDENTICAL), SNAPSHOT, bot_top_role_id=None)
    assert plan.out_of_reach == []
    assert not plan.reorder_blocked


def test_target_order_keeps_unlisted_at_bottom() -> None:
    plan = build_plan(
        parse(WITHOUT_MUTED), SNAPSHOT, bot_top_role_id=BOT_TOP
    )
    assert plan.target_order[-3] == "[Misc]"  # marker listed, keeps spot
    assert plan.target_order[-2] == "🎨 | Blue"
    assert plan.target_order[-1] == "Muted"  # unlisted stays at the bottom
    plan2 = build_plan(
        parse(WITHOUT_MUTED),
        SNAPSHOT,
        bot_top_role_id=BOT_TOP,
        delete=True,
    )
    assert "Muted" not in plan2.target_order


def test_member_counts_in_deletes() -> None:
    plan = build_plan(
        parse(WITHOUT_MUTED),
        SNAPSHOT,
        bot_top_role_id=BOT_TOP,
        delete=True,
        member_counts={8: 7},
    )
    delete = plan.deletes[0]
    assert delete.id == 8
    assert delete.member_count == 7


def test_rename_op_and_member_preservation() -> None:
    manifest = parse(
        "[✨]\n✨ | Caz->✨ | Cazzy : #00a3ff\n"  # rename + keep color
    )
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    (rename,) = plan.renames
    assert (rename.old, rename.new) == ("✨ | Caz", "✨ | Cazzy")
    # the renamed role is matched, not created or deleted
    assert "✨ | Caz" not in [d.name for d in plan.deletes]
    assert "✨ | Caz" not in plan.strays


def test_rename_new_name_already_exists_is_conflict() -> None:
    manifest = parse("[✨]\nOwner->✨ | Caz\n")
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan.renames == []
    assert plan.rename_conflicts == ["✨ | Caz"]


def test_rename_already_applied_is_noop() -> None:
    # "Gone" isn't live but "Owner" is — the rename already happened, so
    # nothing executes, but the manifest line is flagged for cleanup
    manifest = parse("[Staff]\nGone->Owner\n")
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan.renames == []
    assert plan.creates == []  # Owner matched under its new name
    (cleanup,) = plan.cleanup_renames
    assert (cleanup.old, cleanup.new) == ("Gone", "Owner")
    assert not plan.is_clean()  # the manifest line still needs rewriting
    assert not plan.needs_apply  # but nothing needs a Discord mutation
    assert "cleanup 1" in plan.summary()
    assert "cleanup 1 (rename already applied" in plan.render()


def test_rename_keeps_role_out_of_strays() -> None:
    manifest = parse("[Staff]\nOwner\n[✨]\n✨ | Caz->Caz\n")
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert "✨ | Caz" not in plan.strays  # renamed, not a stray
    assert "Muted" in plan.strays  # still unlisted


def test_asset_icon_urls_never_drift() -> None:
    snapshot = [
        cast(
            Any,
            {**dict(r), "icon": "https://cdn.discordapp.com/x.png"},
        )
        for r in SNAPSHOT
    ]
    plan = build_plan(parse(IDENTICAL), snapshot, bot_top_role_id=BOT_TOP)
    assert plan.updates == []  # URL icons can't be managed — not drift


def test_emoji_icon_drift() -> None:
    snapshot = mutated("✨ | Caz", icon="🎨")
    manifest = parse("[✨]\n✨ | Caz : #00a3ff icon:🎨\n")
    plan = build_plan(manifest, snapshot, bot_top_role_id=BOT_TOP)
    assert plan.updates == []  # emoji icons round-trip exactly


def test_rename_hint_for_close_stray() -> None:
    manifest = parse(
        "[Staff]\nOwner\nMutedd\n"  # typo'd — near-identical to live "Muted"
    )
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert ("Muted", "Mutedd") in plan.rename_hints


def test_no_rename_hint_for_unrelated_role() -> None:
    manifest = parse("[Staff]\nOwner\nBrand New Role\n")
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert plan.rename_hints == []


def test_explicit_rename_suppresses_hint() -> None:
    manifest = parse("[Staff]\nOwner\nMuted->Mutedd\n")
    plan = build_plan(manifest, SNAPSHOT, bot_top_role_id=BOT_TOP)
    assert ("Muted", "Mutedd") not in plan.rename_hints
