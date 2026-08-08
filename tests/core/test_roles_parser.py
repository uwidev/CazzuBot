"""Parser for the roles.manifest line format — offline unit tests."""

from __future__ import annotations

import pytest

from cazzubot.roles.parser import (
    Issue,
    Manifest,
    ManifestError,
    parse,
    rewrite_renames,
)

VALID = """\
# comment line
[preset member]
view_channel send_messages add_reactions
read_message_history use_application_commands

[preset mod]
manage_roles manage_messages kick_members ban_members

[👀 Staff]
Owner
Admin Baka : mentionable +administrator
Mod Baka : hoist mentionable preset:mod -ban_members
Caz : #0a6fb3
Short : #abc
Iconed : icon:🎮
"""


def test_parse_happy_path() -> None:
    manifest = parse(VALID)
    assert isinstance(manifest, Manifest)
    assert [g.title for g in manifest.groups] == ["👀 Staff"]
    roles = manifest.groups[0].roles
    assert [r.name for r in roles] == [
        "Owner",
        "Admin Baka",
        "Mod Baka",
        "Caz",
        "Short",
        "Iconed",
    ]
    assert manifest.presets["mod"].flags == {
        "manage_roles",
        "manage_messages",
        "kick_members",
        "ban_members",
    }


def test_effective_permissions_preset_plus_minus() -> None:
    manifest = parse(VALID)
    mod = next(r for r in manifest.groups[0].roles if r.name == "Mod Baka")
    assert manifest.effective_permissions(mod) == {
        "manage_roles",
        "manage_messages",
        "kick_members",
    }  # ban_members revoked
    admin = next(
        r for r in manifest.groups[0].roles if r.name == "Admin Baka"
    )
    assert manifest.effective_permissions(admin) == {"administrator"}


def test_hex3_expansion_and_icon() -> None:
    manifest = parse(VALID)
    short = next(r for r in manifest.groups[0].roles if r.name == "Short")
    assert short.color == "#aabbcc"
    iconed = next(
        r for r in manifest.groups[0].roles if r.name == "Iconed"
    )
    assert iconed.icon == "🎮"


def test_named_color() -> None:
    manifest = parse("""[x]\nRole : red\n""")
    assert manifest.groups[0].roles[0].color == "#e74c3c"


def test_preset_order_independent() -> None:
    manifest = parse(
        """[x]\nRole : preset:later\n\n[preset later]\nmanage_roles\n"""
    )
    assert manifest.groups[0].roles[0].preset == "later"


def test_blank_lines_and_comments_ignored() -> None:
    manifest = parse("   \n# only a comment\n\n[x]\n\nRole\n")
    assert manifest.role_names() == ("Role",)


def test_errors_are_collected_with_lines() -> None:
    with pytest.raises(ManifestError) as exc:
        parse(
            "[preset mod]\n"
            "manage_roles\n"
            "\n"
            "[Stuff]\n"
            "Role A : #12345\n"
            "Role B : manage_mesages\n"
            "[preset Mod]\n"
        )
    issues = exc.value.issues
    assert len(issues) == 3
    assert Issue(5, "invalid color '#12345'") in issues
    assert any(
        "did you mean 'manage_messages'" in i.message for i in issues
    )
    assert any("invalid preset name 'Mod'" in i.message for i in issues)


def test_duplicate_role_name() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\nRole\nRole\n")
    assert any("duplicate role" in i.message for i in exc.value.issues)


def test_duplicate_preset_name() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[preset p]\nmanage_roles\n\n[preset p]\nview_channel\n")
    assert any("duplicate preset" in i.message for i in exc.value.issues)


def test_unknown_preset_reference() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\nRole : preset:nope\n")
    assert any("unknown preset" in i.message for i in exc.value.issues)


def test_duplicate_color_token() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\nRole : #aabbcc red\n")
    assert any("duplicate color" in i.message for i in exc.value.issues)


def test_empty_group_is_allowed() -> None:
    # a [Group] header with no members is a marker role with an empty span
    manifest = parse("[x]\n")
    (group,) = manifest.groups
    assert group.title == "x"
    assert group.roles == ()
    assert manifest.ordered_names() == ("[x]",)


def test_headerless_roles_form_implicit_group() -> None:
    manifest = parse("Role before any group\nOther Role\n")
    (group,) = manifest.groups
    assert group.title is None
    assert manifest.role_names() == ("Role before any group", "Other Role")
    assert manifest.ordered_names() == (
        "Role before any group",
        "Other Role",
    )


def test_ordered_names_interleaves_markers() -> None:
    manifest = parse("[Staff]\nOwner\n[Vanity]\nCaz : #00a3ff\n")
    assert manifest.ordered_names() == (
        "[Staff]",
        "Owner",
        "[Vanity]",
        "Caz",
    )


def test_duplicate_group_title_is_error() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[Staff]\nA\n[Staff]\nB\n")
    assert any("duplicate group" in i.message for i in exc.value.issues)


def test_blank_line_ends_preset_section() -> None:
    # header-less role lines may follow a preset after a blank line
    manifest = parse(
        "[preset member]\nview_channel send_messages\n\nMuted\nRole Two\n"
    )
    assert manifest.presets["member"].flags == {
        "view_channel",
        "send_messages",
    }
    assert manifest.role_names() == ("Muted", "Role Two")


def test_role_line_inside_preset_errors_with_hint() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[preset member]\nview_channel\nMuted\n")
    assert any("blank line" in i.message for i in exc.value.issues)


def test_rename_chain_is_error() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\nA->B\nB->C\n")
    assert any("rename chain" in i.message for i in exc.value.issues)


def test_rename_from_marker_is_error() -> None:
    # a marker-shaped old name can't even be expressed as a rename line —
    # "[Staff]->Renamed" parses as a malformed header
    with pytest.raises(ManifestError) as exc:
        parse("[Staff]\n[Staff]->Renamed\n")
    assert any("unclosed" in i.message for i in exc.value.issues)


def test_padded_role_name_is_error() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\nRole Name  : #aabbcc\n")  # trailing pad before " : "
    assert any("whitespace" in i.message for i in exc.value.issues)


def test_everyone_is_reserved() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\n@everyone\n")
    assert any("reserved" in i.message for i in exc.value.issues)


def test_line_outside_section() -> None:
    # header-less role lines are allowed — they form an implicit group
    manifest = parse("Role before any group\n")
    assert manifest.role_names() == ("Role before any group",)


def test_preset_prefix_commits_to_preset_section() -> None:
    # "[preset Stuff]" is a preset attempt with a bad name, not a group
    with pytest.raises(ManifestError) as exc:
        parse("[preset Stuff]\n")
    assert any(
        "invalid preset name" in i.message for i in exc.value.issues
    )


def test_unknown_flag_in_preset() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[preset p]\nnot_a_flag\n")
    assert any("unknown permission" in i.message for i in exc.value.issues)


def test_rename_marker() -> None:
    manifest = parse("[x]\nOld Name->New Name : hoist mentionable\n")
    (spec,) = manifest.groups[0].roles
    assert spec.name == "New Name"
    assert spec.renamed_from == "Old Name"
    assert spec.hoist and spec.mentionable
    assert manifest.renames() == ((2, "Old Name", "New Name"),)


def test_rename_with_spaces_around_arrow() -> None:
    manifest = parse("[x]\nOld Name -> New Name\n")
    (spec,) = manifest.groups[0].roles
    assert (spec.renamed_from, spec.name) == ("Old Name", "New Name")


def test_rename_noop_is_error() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\nSame->Same\n")
    assert any("no-op" in i.message for i in exc.value.issues)


def test_rename_empty_side_is_error() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\n->New Name\n")
    assert any("no old name" in i.message for i in exc.value.issues)
    with pytest.raises(ManifestError) as exc:
        parse("[x]\nOld Name->\n")
    assert any("no new name" in i.message for i in exc.value.issues)


def test_rename_collides_with_plain_role() -> None:
    with pytest.raises(ManifestError) as exc:
        parse("[x]\nOld->New\nNew\n")
    assert any("duplicate role" in i.message for i in exc.value.issues)


def test_rewrite_renames_preserves_rest_of_file() -> None:
    text = (
        "# header\n"
        "[👀]\n"
        "Old Name->New Name : hoist\n"
        "Plain Role\n"
        "Old Two -> New Two : preset:member\n"
        "# tail\n"
        "# vim: ft=txt :\n"
    )
    rewritten = rewrite_renames(text, [(3, "Old Name", "New Name")])
    assert "New Name : hoist\n" in rewritten
    assert "Old Name->New Name" not in rewritten
    assert "Old Two -> New Two : preset:member\n" in rewritten
    assert rewritten.startswith("# header\n")
    assert rewritten.endswith("# tail\n# vim: ft=txt :\n")
