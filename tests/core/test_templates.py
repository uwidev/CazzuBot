# pyright: reportArgumentType=false
"""Template verification — ported from scripts/functest.py."""

from __future__ import annotations

import json

import hikari
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


# -- send: least-permissive mention parsing --------------------------------


async def test_send_mentions_only_those_present() -> None:
    """Least-permissive: only users/roles actually written get parse rights,
    never a blanket "all users"/"all roles"."""
    channel = FakeChannel(id=1)
    await templates.send(
        channel, {"content": "hi <@424242> and <@&777>"}
    )
    sent = channel.sent[-1]
    assert sent["user_mentions"] == [424242]
    assert sent["role_mentions"] == [777]
    assert sent["mentions_everyone"] is hikari.UNDEFINED


async def test_send_no_mentions_means_no_parsing() -> None:
    """A message with no user/role mentions gets no parse entries."""
    channel = FakeChannel(id=1)
    await templates.send(channel, {"content": "plain text"})
    sent = channel.sent[-1]
    assert sent["user_mentions"] is hikari.UNDEFINED
    assert sent["role_mentions"] is hikari.UNDEFINED
    assert sent["mentions_everyone"] is hikari.UNDEFINED


async def test_send_extracts_mentions_from_embeds() -> None:
    """Mentions inside embed text fields are scanned too."""
    channel = FakeChannel(id=1)
    await templates.send(
        channel,
        {
            "content": "plain",
            "embed": {"description": "hi <@424242> and <@&777>"},
        },
    )
    sent = channel.sent[-1]
    assert sent["user_mentions"] == [424242]
    assert sent["role_mentions"] == [777]


async def test_send_allowed_mentions_true_allows_present_everyone() -> None:
    """``allowed_mentions: true`` + ``@everyone``/``@here`` present → enabled;
    without @everyone in the text it stays off."""
    channel = FakeChannel(id=1)
    await templates.send(
        channel, {"content": "hi @everyone", "allowed_mentions": True}
    )
    sent = channel.sent[-1]
    assert sent["user_mentions"] is hikari.UNDEFINED
    assert sent["role_mentions"] is hikari.UNDEFINED
    assert sent["mentions_everyone"] is True

    await templates.send(
        channel, {"content": "hi", "allowed_mentions": True}
    )
    sent = channel.sent[-1]
    assert sent["mentions_everyone"] is hikari.UNDEFINED


async def test_send_allowed_mentions_false_parses_nothing() -> None:
    """``allowed_mentions: false`` suppresses parsing entirely."""
    channel = FakeChannel(id=1)
    await templates.send(
        channel,
        {"content": "hi <@424242>", "allowed_mentions": False},
    )
    sent = channel.sent[-1]
    assert "user_mentions" not in sent
    assert "role_mentions" not in sent
    assert "mentions_everyone" not in sent


async def test_send_caller_mention_kwargs_win() -> None:
    """Caller-supplied mention kwargs override the template-derived values."""
    channel = FakeChannel(id=1)
    await templates.send(
        channel,
        {"content": "hi <@424242> @everyone", "allowed_mentions": True},
        user_mentions=False,
        mentions_everyone=False,
    )
    sent = channel.sent[-1]
    assert sent["user_mentions"] is False
    assert sent["role_mentions"] is hikari.UNDEFINED
    assert sent["mentions_everyone"] is False
