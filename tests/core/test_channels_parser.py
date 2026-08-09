"""Channels manifest parser — offline unit tests (no discord connection)."""

from __future__ import annotations

import pytest

from cazzubot.channels.parser import ManifestError, parse
from cazzubot.manifest.lines import rewrite_renames


def issues(text: str) -> list[str]:
    with pytest.raises(ManifestError) as exc:
        parse(text)
    return [str(issue) for issue in exc.value.issues]


def test_headers_and_plain_channels() -> None:
    m = parse(
        """\
[Activities]
gaming
general : slowmode:30

[Info]
rules
"""
    )
    assert [g.title for g in m.groups] == ["Activities", "Info"]
    assert [c.name for c in m.groups[0].channels] == [
        "gaming",
        "general",
    ]
    assert m.groups[0].channels[1].slowmode == 30
    assert m.channel_names() == ("gaming", "general", "rules")


def test_uncategorized_implicit_group() -> None:
    m = parse("welcome\n[Info]\nrules\n")
    assert m.groups[0].title is None
    assert [c.name for c in m.groups[0].channels] == ["welcome"]
    assert m.groups[1].title == "Info"


def test_tokens() -> None:
    m = parse(
        "vc : type:voice nsfw slowmode:0 bitrate:96 limit:10 "
        "region:us-west quality:1080\n"
        "chat : slowmode:15\n"
        "news : type:announcement nsfw\n"
        "board : type:forum slowmode:60\n"
        "stage : type:stage bitrate:64\n"
    )
    vc = m.groups[0].channels[0]
    assert (vc.kind, vc.nsfw, vc.bitrate, vc.limit) == (
        "voice",
        True,
        96,
        10,
    )
    assert (vc.region, vc.quality) == ("us-west", "1080")
    chat = m.groups[0].channels[1]
    assert (chat.kind, chat.slowmode) == ("text", 15)
    assert m.groups[0].channels[2].kind == "announcement"
    assert m.groups[0].channels[3].kind == "forum"
    assert m.groups[0].channels[4].kind == "stage"


def test_default_kind_is_text() -> None:
    assert parse("hello\n").groups[0].channels[0].kind == "text"


def test_unknown_token() -> None:
    errs = issues("hello : hoist\n")
    assert any("unknown token 'hoist'" in e for e in errs)


def test_unknown_channel_type() -> None:
    errs = issues("hello : type:telepathy\n")
    assert any("invalid channel type 'telepathy'" in e for e in errs)


def test_type_category_rejected_on_lines() -> None:
    errs = issues("hello : type:category\n")
    assert any("invalid channel type 'category'" in e for e in errs)


def test_slowmode_on_voice_rejected() -> None:
    errs = issues("vc : type:voice slowmode:30\n")
    assert any("slowmode doesn't apply to voice" in e for e in errs)


def test_voice_attrs_on_text_rejected() -> None:
    errs = issues("chat : bitrate:96\n")
    assert any("only apply to voice channels" in e for e in errs)


def test_slowmode_range() -> None:
    errs = issues("chat : slowmode:99999\n")
    assert any("exceeds the 6h maximum" in e for e in errs)
    errs2 = issues("chat : slowmode:abc\n")
    assert any("invalid slowmode" in e for e in errs2)


def test_bitrate_limit_quality_validation() -> None:
    assert any(
        "invalid bitrate" in e
        for e in issues("vc : type:voice bitrate:0\n")
    )
    assert any(
        "invalid user limit" in e
        for e in issues("vc : type:voice limit:100000\n")
    )
    assert any(
        "invalid video quality" in e
        for e in issues("vc : type:voice quality:4k\n")
    )


def test_duplicate_channel() -> None:
    errs = issues("[A]\nx\nx\n")
    assert any("duplicate channel 'x'" in e for e in errs)


def test_duplicate_category() -> None:
    errs = issues("[A]\nx\n[A]\ny\n")
    assert any("duplicate category 'A'" in e for e in errs)


def test_bracketed_line_is_header_not_channel() -> None:
    # channel names must not be bracket-wrapped — such a line is a header
    m = parse("[A]\n[B]\nx\n")
    assert [g.title for g in m.groups] == ["A", "B"]


def test_header_with_tokens_rejected() -> None:
    # a header line that also carries tokens can't close cleanly
    errs = issues("[A] : nsfw\nx\n")
    assert any("unclosed section header" in e for e in errs)


def test_whitespace_in_name_rejected() -> None:
    errs = issues(" padded \n")
    assert any("leading/trailing whitespace" in e for e in errs)


def test_rename_lines() -> None:
    m = parse("[A]\nold->new\n")
    spec = m.groups[0].channels[0]
    assert (spec.renamed_from, spec.name) == ("old", "new")
    assert m.renames() == ((2, "old", "new"),)


def test_rename_no_tokens_trailing_colon() -> None:
    # ``Name -> New :`` with no tokens — strip() eats the trailing space
    m = parse("[A]\nold->new :\n")
    spec = m.groups[0].channels[0]
    assert (spec.renamed_from, spec.name) == ("old", "new")
    assert spec.kind == "text"


def test_rename_with_tokens() -> None:
    m = parse("[A]\nold->new : nsfw\n")
    spec = m.groups[0].channels[0]
    assert (spec.renamed_from, spec.name, spec.nsfw) == (
        "old",
        "new",
        True,
    )


def test_rename_errors() -> None:
    assert any("no old name" in e for e in issues("[A]\n->new\n"))
    assert any("no new name" in e for e in issues("[A]\nold->\n"))
    assert any("no-op" in e for e in issues("[A]\nold->old\n"))


def test_rename_chain_rejected() -> None:
    errs = issues("[A]\na->b\nb->c\n")
    assert any("rename chain not supported" in e for e in errs)


def test_rename_target_with_arrow_rejected() -> None:
    errs = issues("[A]\na->b->c\n")
    assert any("renames can't chain" in e for e in errs)


def test_rename_target_unroundtrippable_rejected() -> None:
    errs = issues("[A]\na->[bracket\n")
    assert any("can't round-trip" in e for e in errs)


def test_duplicate_rename_source_rejected() -> None:
    errs = issues("[A]\na->b\na->c\n")
    assert any("duplicate rename source" in e for e in errs)


def test_comments_and_blanks_ignored() -> None:
    m = parse(
        "# header comment\n\n[Info]\n# inner comment\nrules\n\n"
        "memes : # trailing comment\n"
    )
    assert [c.name for c in m.groups[0].channels] == ["rules", "memes"]


def test_rewrite_renames_preserves_rest() -> None:
    text = "# c\n[Info]\nold->new : nsfw\nrules\n# vim: ft=txt :\n"
    out = rewrite_renames(text, [(3, "old", "new")])
    assert out == "# c\n[Info]\nnew : nsfw\nrules\n# vim: ft=txt :\n"
