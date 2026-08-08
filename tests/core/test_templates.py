"""Template verification — ported from scripts/functest.py."""

from __future__ import annotations

import json

import pytest

from cazzubot import templates, utils
from cazzubot.errors import UserInputError
from plugins.levels.logic import formatter
from tests.fakes import FakeMember


def test_verify_accepts_valid_template_with_formatter() -> None:
    msg: dict[str, object] = {
        "content": "hi {mention}",
        "embed": {
            "title": "t",
            "description": "{name}",
            "fields": [],
        },
    }
    valid = templates.verify(
        json.dumps(msg),
        formatter,
        member=utils.member_snapshot(FakeMember(id=123, name="cirno")),
    )
    assert valid["embed"]["description"] == "{name}"


def test_verify_rejects_invalid_templates() -> None:
    # validation only runs when a formatter is supplied (dry-run path)
    member = utils.member_snapshot(FakeMember(id=123, name="cirno"))
    with pytest.raises(UserInputError):
        templates.verify('{"bogus_key": 1}', formatter, member=member)
    with pytest.raises(UserInputError):
        templates.verify('{"content": 42}', formatter, member=member)


def test_prepare_returns_plain_json_not_framework_objects() -> None:
    """Pin the hikari seam: prepare() never yields discord objects."""
    content, embed, embeds = templates.prepare(
        {"content": "hi", "embed": {"title": "t"}}
    )
    assert content == "hi"
    assert embed == {"title": "t"}
    assert isinstance(embed, dict)
    assert embeds == []


def test_prepare_single_embed_wins_over_embeds() -> None:
    content, embed, embeds = templates.prepare(
        {
            "embed": {"title": "single"},
            "embeds": [{"title": "first"}, {"title": "second"}],
        }
    )
    assert embed == {"title": "single"}
    assert embeds == []


def test_prepare_empty_message_gets_placeholder() -> None:
    content, embed, embeds = templates.prepare({"content": ""})
    assert content == "_ _"
    assert embed is None
    assert embeds == []


def test_prepare_drops_empty_embed_dicts_like_old_filtering() -> None:
    """Regression: ``{}`` embeds degrade to the content fallback (the old
    ``discord.Embed.from_dict`` filtering did the same)."""
    content, embed, embeds = templates.prepare({"embed": {}})
    assert content == "_ _"
    assert embed is None
    content, embed, embeds = templates.prepare({"embeds": [{}]})
    assert content == "_ _"
    assert embed is None
    assert embeds == []


def test_prepare_keeps_color_only_embed() -> None:
    """A valid embed that only sets color is a non-empty dict and survives."""
    content, embed, embeds = templates.prepare({"embed": {"color": 12345}})
    assert embed == {"color": 12345}
    assert embeds == []
