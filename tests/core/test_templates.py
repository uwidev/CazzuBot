"""Template verification — ported from scripts/functest.py."""

from __future__ import annotations

import json

import pytest
from discord.ext import commands

from cazzubot import templates
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
        json.dumps(msg), formatter, member=FakeMember(id=123, name="cirno")
    )
    assert valid["embed"]["description"] == "{name}"


def test_verify_rejects_invalid_templates() -> None:
    # validation only runs when a formatter is supplied (dry-run path)
    member = FakeMember(id=123, name="cirno")
    with pytest.raises(commands.BadArgument):
        templates.verify('{"bogus_key": 1}', formatter, member=member)
    with pytest.raises(commands.BadArgument):
        templates.verify('{"content": 42}', formatter, member=member)
