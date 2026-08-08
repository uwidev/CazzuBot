"""Channels manifest export — offline unit tests (no discord connection)."""

from __future__ import annotations

from typing import Any, cast

from cazzubot.channels.export import render_manifest
from cazzubot.channels.snapshot import ChannelSnapshot
from cazzubot.channels.parser import parse
from cazzubot.channels.plan import build_plan


def ch(
    id: str,
    name: str,
    kind: str = "text",
    cat: str | None = None,
    pos: int = 0,
    nsfw: bool = False,
    slow: int = 0,
    **voice: object,
) -> ChannelSnapshot:
    d: ChannelSnapshot = {
        "id": id,
        "name": name,
        "kind": kind,
        "category": cat,
        "position": pos,
        "nsfw": nsfw,
        "slowmode": slow,
    }
    if kind in ("voice", "stage"):
        d.update(
            bitrate=64,
            limit=0,
            region=None,
            quality="auto",
        )
    d.update(cast(Any, voice))
    return d


SNAPSHOT: list[ChannelSnapshot] = [
    ch("0", "welcome"),
    ch("1", "general", slow=5),
    ch("2", "lobby", "voice"),
    ch("3", "Games", "category"),
    ch("4", "minecraft", cat="Games"),
    ch("5", "voice-chat", "voice", cat="Games", bitrate=96),
    ch("6", "Info", "category", pos=1),
    ch("7", "rules", cat="Info"),
    ch("8", "announcements", "announcement", cat="Info", pos=1),
]


def rendered() -> str:
    return render_manifest(SNAPSHOT)


def body_lines() -> list[str]:
    lines = rendered().splitlines()
    return [ln for ln in lines if not ln.startswith("#") and ln]


def test_renders_categories_and_channels() -> None:
    lines = body_lines()
    assert lines[0] == "welcome"
    assert lines[1] == "general : slowmode:5"
    assert lines[2] == "lobby : type:voice"
    assert lines[3] == "[Games]"
    assert lines[4] == "minecraft"
    assert lines[5] == "voice-chat : type:voice bitrate:96"
    assert lines[6] == "[Info]"
    assert lines[7] == "rules"
    assert lines[8] == "announcements : type:announcement"


def test_defaults_are_omitted() -> None:
    body = "\n".join(body_lines())
    # slowmode 0 / nsfw False / text kind / default bitrate, limit,
    # region, quality never appear on channel lines
    assert "nsfw" not in body
    assert "slowmode:0" not in body
    assert "type:text" not in body
    assert "bitrate:64" not in body
    assert "limit:0" not in body
    assert "region:" not in body
    assert "quality:auto" not in body


def test_non_default_voice_attrs_render() -> None:
    assert "bitrate:96" in rendered()


def test_round_trip_is_clean() -> None:
    manifest = parse(rendered())
    plan = build_plan(manifest, SNAPSHOT)
    assert plan.is_clean(), plan.render()


def test_cheatsheet_mentions_scope() -> None:
    text = rendered()
    assert "channels.manifest" in text
    assert "# vim: ft=txt :" in text
    assert "category" in text.lower()


def test_unsupported_kind_rendered_as_is() -> None:
    snap = SNAPSHOT + [ch("9", "odd", "unknown_kind")]
    text = render_manifest(snap)
    assert "odd" in text


def test_unrepresentable_names_kept_as_is() -> None:
    from cazzubot.channels.executor import _representable_name

    assert _representable_name("normal-name")
    assert not _representable_name("a->b")
    assert not _representable_name("has : space")
    assert not _representable_name("ends :")
    assert not _representable_name(" padded")
    assert not _representable_name("[bracketed]")
    assert not _representable_name("[unclosed")
    assert not _representable_name("#commenty")
    assert not _representable_name("   ")
