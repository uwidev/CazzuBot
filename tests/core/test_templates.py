# pyright: reportArgumentType=false
"""Template verification — ported from scripts/functest.py."""

from __future__ import annotations

import json

import pytest

from cazzubot import templates, utils
from cazzubot.errors import UserInputError
from plugins.levels.logic import formatter
from tests.fakes import FakeChannel, FakeMember


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


# -- send: mention parsing (the "Unknown User" welcome fix) ----------------


async def test_send_default_parses_users_and_roles() -> None:
    """Absent ``allowed_mentions`` → users + roles parsed, no @everyone."""
    channel = FakeChannel(id=1)
    await templates.send(channel, {"content": "hi {mention}"})
    sent = channel.sent[-1]
    assert sent["user_mentions"] is True
    assert sent["role_mentions"] is True
    assert "mentions_everyone" not in sent


async def test_send_allowed_mentions_true_adds_everyone() -> None:
    channel = FakeChannel(id=1)
    await templates.send(
        channel, {"content": "hi", "allowed_mentions": True}
    )
    sent = channel.sent[-1]
    assert sent["user_mentions"] is True
    assert sent["role_mentions"] is True
    assert sent["mentions_everyone"] is True


async def test_send_allowed_mentions_false_parses_nothing() -> None:
    channel = FakeChannel(id=1)
    await templates.send(
        channel, {"content": "hi", "allowed_mentions": False}
    )
    sent = channel.sent[-1]
    assert "user_mentions" not in sent
    assert "role_mentions" not in sent
    assert "mentions_everyone" not in sent


async def test_send_caller_mention_kwargs_win() -> None:
    channel = FakeChannel(id=1)
    await templates.send(
        channel,
        {"content": "hi", "allowed_mentions": True},
        user_mentions=False,
    )
    sent = channel.sent[-1]
    assert sent["user_mentions"] is False
    assert sent["role_mentions"] is True
    assert sent["mentions_everyone"] is True
