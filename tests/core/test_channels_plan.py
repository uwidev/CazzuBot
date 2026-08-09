"""Channels plan engine — offline unit tests (no discord connection)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from cazzubot.channels.parser import parse
from cazzubot.channels.plan import build_plan
from tests.core.channels_data import SNAPSHOT, ch, mutated

IDENTICAL = """\
welcome
general : slowmode:5
lobby : type:voice

[Games]
minecraft
voice-chat : type:voice bitrate:96

[Info]
rules
announcements : type:announcement
"""


def plan(text: str = IDENTICAL, **kwargs):
    return build_plan(parse(text), SNAPSHOT, **kwargs)


def test_clean_manifest() -> None:
    p = plan()
    assert p.is_clean()
    assert p.needs_reorder is False
    assert "clean" in p.render()


def test_missing_category_is_create() -> None:
    p = plan("welcome\n[New]\nchat\n")
    assert [op.spec.name for op in p.creates] == ["New", "chat"]
    assert p.creates[0].spec.kind == "category"
    assert p.creates[1].category == "New"


def test_create_channel_under_category() -> None:
    p = plan("[Games]\nminecraft\nvoice-chat : type:voice\nbrand-new\n")
    create = p.creates[0]
    assert create.spec.name == "brand-new"
    assert create.category == "Games"
    assert p.needs_reorder  # the new channel must be positioned


def test_attr_updates() -> None:
    p = plan(
        "welcome\n[Games]\nminecraft\nvoice-chat : type:voice bitrate:128\n"
    )
    assert [op.name for op in p.updates] == ["voice-chat"]
    assert p.updates[0].changes["bitrate"] == (96, 128)


def test_slowmode_and_nsfw_updates() -> None:
    p = plan("welcome\n[Games]\nminecraft : nsfw slowmode:10\n")
    assert p.updates[0].changes["nsfw"] == (False, True)
    assert p.updates[0].changes["slowmode"] == (0, 10)


def test_voice_default_attrs_not_drift() -> None:
    # manifest omits defaults: 64 kbps, unlimited, auto — no drift
    p = plan("welcome\nlobby : type:voice\n")
    assert p.updates == []


def test_text_announcement_convert_is_update() -> None:
    p = plan("[Info]\nrules\nannouncements\n")
    assert [op.name for op in p.updates] == ["announcements"]
    assert p.updates[0].changes["kind"] == ("announcement", "text")


def test_unsupported_kind_change() -> None:
    p = plan("[Games]\nminecraft : type:voice\n")
    assert p.type_changes == ["minecraft"]
    assert not p.is_clean()


def test_deletes_require_flag_and_skip_categories() -> None:
    p = plan(
        "welcome\n[Games]\nminecraft\n",
        delete=False,
    )
    assert p.deletes == []
    assert "lobby" in p.strays
    assert p.stray_categories == ["Info"]
    p2 = plan(
        "welcome\n[Games]\nminecraft\n",
        delete=True,
    )
    names = [d.name for d in p2.deletes]
    assert "lobby" in names
    assert "Info" not in names  # a category with children is never deleted


def test_empty_stray_category_is_delete_candidate() -> None:
    snap = SNAPSHOT + [ch("9", "Empty", "category", pos=2)]
    p = build_plan(parse(IDENTICAL), snap, delete=True)
    assert [d.name for d in p.deletes] == ["Empty"]


def test_strays_do_not_force_reorder() -> None:
    # a stray in the middle must not keep the plan perpetually dirty
    snap = SNAPSHOT + [ch("9", "stray", cat="Games", pos=1)]
    p = build_plan(parse(IDENTICAL), snap)
    assert p.strays == ["stray"]
    assert not p.needs_reorder


def test_reorder_swap_within_category() -> None:
    snap = [cast(Any, dict(c)) for c in SNAPSHOT]
    snap[7]["position"], snap[8]["position"] = 1, 0  # rules/announcements
    p = build_plan(parse(IDENTICAL), snap)
    assert p.needs_reorder


def test_category_reorder() -> None:
    snap = [cast(Any, dict(c)) for c in SNAPSHOT]
    snap[3]["position"], snap[6]["position"] = 1, 0
    p = build_plan(parse(IDENTICAL), snap)
    assert p.needs_reorder
    assert (None, "category") in p.target


def test_channel_moved_between_categories() -> None:
    p = plan(
        "welcome\n[Info]\nrules\nannouncements : type:announcement\nminecraft\n"
    )
    assert p.needs_reorder
    assert ("Games", "text") not in p.target
    assert ("Info", "text") in p.target


def test_rename_op() -> None:
    p = plan("welcome\n[Games]\nminecraft->mc\n")
    (op,) = p.renames
    assert (op.old, op.new) == ("minecraft", "mc")
    assert "minecraft" not in p.strays


def test_rename_conflict() -> None:
    # renaming onto a live name the manifest also addresses (a category
    # title) is a conflict
    p = plan("welcome\n[Games]\nwelcome->Games\n")
    assert p.renames == []
    assert p.rename_conflicts == ["Games"]


def test_rename_onto_unlisted_live_name_is_allowed() -> None:
    # the new name exists live but the manifest does not address it — the
    # rename proceeds and the existing holder becomes a duplicate
    p = plan("welcome\n[Games]\nwelcome->minecraft\n")
    (op,) = p.renames
    assert (op.old, op.new) == ("welcome", "minecraft")
    assert p.rename_conflicts == []


def test_rename_already_applied_is_cleanup() -> None:
    p = plan("welcome\n[Games]\ngone->minecraft\n")
    assert p.renames == []
    assert p.creates == []
    (cleanup,) = p.cleanup_renames
    assert (cleanup.old, cleanup.new) == ("gone", "minecraft")
    assert not p.is_clean()
    assert not p.needs_apply


def test_rename_hint_for_close_stray() -> None:
    p = plan("welcome\n[Games]\nminecraaft\n")
    assert ("minecraft", "minecraaft") in p.rename_hints


def test_duplicate_live_names_kept_unsupported() -> None:
    # Discord allows duplicate names; the engine manages only the first
    # and reports the rest as unsupported (never deleted, never reordered)
    snap = SNAPSHOT + [
        ch("9", "rules", cat="Info", pos=2, unsupported=True)
    ]
    p = build_plan(parse(IDENTICAL), snap, delete=True)
    assert p.is_clean() or not p.deletes
    assert "rules" in p.unsupported
    assert p.strays == []
    assert not p.needs_reorder


def test_out_of_scope_manifest_channel_inside_scope_not_deleted() -> None:
    # a channel declared above the boundary (out of scope) but physically
    # sitting inside an in-scope category must never become a delete
    # candidate — the manifest still governs it
    snap = mutated("welcome", category="Games")
    p = build_plan(
        parse(IDENTICAL),
        snap,
        scope_below="Games",
        delete=True,
    )
    assert "welcome" in p.out_of_scope
    assert "welcome" not in p.strays
    assert all(d.name != "welcome" for d in p.deletes)


def test_scope_name_collision_never_touches_out_of_scope() -> None:
    # an out-of-scope channel whose name matches an in-scope manifest
    # name must never be updated/renamed/moved — the plan treats the
    # name as missing and excludes the id from in_scope_ids
    snap = mutated("minecraft", category=None)
    # minecraft physically sits ABOVE the boundary (uncategorized)
    p = build_plan(
        parse(IDENTICAL),
        snap,
        scope_below="Games",
        delete=True,
    )
    assert "minecraft" not in p.out_of_scope  # it IS listed in-scope
    assert "minecraft" in [op.spec.name for op in p.creates]
    assert p.updates == []
    assert "minecraft" not in p.strays
    live_id = int(
        cast(str, next(c["id"] for c in snap if c["name"] == "minecraft"))
    )
    assert live_id not in p.in_scope_ids


def test_in_scope_ids_only_managed_listed_channels() -> None:
    p = plan(scope_below="Games")
    # welcome/general/lobby are out of scope; only in-scope managed,
    # listed channels (incl. the in-scope categories) make the set
    expected = {
        int(c["id"])
        for c in SNAPSHOT
        if c["name"]
        in {
            "Games",
            "Info",
            "minecraft",
            "voice-chat",
            "rules",
            "announcements",
        }
    }
    assert set(p.in_scope_ids) == expected


def test_only_unsupported_occurrence_excluded_from_target() -> None:
    # a manifest name whose only live occurrence is unsupported must not
    # cause a permanent reorder drift
    snap = SNAPSHOT + [ch("9", "ghost", unsupported=True)]
    p = build_plan(
        parse(
            "welcome\n[Games]\nminecraft\nvoice-chat : type:voice\n"
            "ghost\n[Info]\nrules\nannouncements : type:announcement\n"
        ),
        snap,
    )
    assert "ghost" in p.unsupported
    assert "ghost" not in {
        n for _, names in p.target.items() for n in names
    }
    assert not p.needs_reorder


def test_children_of_duplicate_category_never_deleted() -> None:
    # channels inside a duplicate (non-first) category are unaddressable
    # by name — marked unsupported at snapshot time, they must never
    # become strays or delete candidates even when the category name is
    # an in-scope manifest title
    snap = SNAPSHOT + [
        ch("9", "Games", "category", pos=2, unsupported=True),
        ch("10", "secret", cat="Games", unsupported=True),
    ]
    p = build_plan(
        parse(IDENTICAL),
        snap,
        scope_below="Games",
        delete=True,
    )
    assert "secret" in p.unsupported
    assert "secret" not in p.strays
    assert all(d.name != "secret" for d in p.deletes)
    assert "Games" not in p.stray_categories


def test_category_title_held_by_non_category_blocks_apply() -> None:
    # a manifest [title] whose name is held by a live non-category
    # channel (Discord allows channel/category name collisions) must
    # block apply instead of misplacing children
    snap = mutated("Games", kind="text")
    p = build_plan(parse(IDENTICAL), snap)
    assert "Games" in p.type_changes
    assert not p.is_clean()


def test_scope_below_keeps_top_untouched() -> None:
    p = plan(scope_below="Games")
    assert p.is_clean()
    assert set(p.out_of_scope) == {"welcome", "general", "lobby"}


def test_scope_below_strays_only_in_scope() -> None:
    p = plan(
        "welcome\n[Games]\nminecraft\n",
        scope_below="Games",
        delete=True,
    )
    assert [d.name for d in p.deletes] == ["voice-chat"]
    # out-of-scope channels are not strays and never deleted: manifest
    # names above the boundary are reported; live-only channels above
    # (general/lobby) are simply never mentioned
    assert "welcome" not in p.strays
    assert "general" not in p.strays
    assert "welcome" in p.out_of_scope


def test_scope_below_missing_group_raises() -> None:
    with pytest.raises(ValueError, match="not found in the manifest"):
        plan(scope_below="Nope")


def test_scope_rename_in_scope_only() -> None:
    p = plan(
        "welcome\n[Games]\nvoice-chat->vc : type:voice\nminecraft\n[Info]\nrules\nannouncements : type:announcement\n",
        scope_below="Games",
    )
    (op,) = p.renames
    assert (op.old, op.new) == ("voice-chat", "vc")
