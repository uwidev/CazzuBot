"""Shared fixtures: a real booted bot against a temp sqlite database.

Same pattern as ``scripts/smoke.py`` / ``functest.py``: build a ``CazzuBot``
with a fake config, patch ``wait_until_ready`` so no Discord connection is
attempted, and run ``setup_hook`` so plugins, schemas, scheduler and command
tree are all live.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from cazzubot import CazzuBot, Config
from cazzubot.db import Database

from tests.fakes import (
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeMember,
)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncGenerator[Database, None]:
    """A bare connected Database (repository-layer tests)."""
    instance = Database(str(tmp_path / "data.db"))
    await instance.connect()
    yield instance
    await instance.close()


@pytest.fixture
async def bot(tmp_path: Path) -> AsyncGenerator[CazzuBot, None]:
    instance = CazzuBot(
        Config(
            token="fake-token",
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "test.db"),
        )
    )

    async def _ready() -> None:
        pass

    instance.wait_until_ready = _ready  # type: ignore[method-assign]
    await instance.setup_hook()
    yield instance
    await instance.close()


@pytest.fixture
def fake_guild() -> FakeGuild:
    return FakeGuild(id=2, owner_id=1)


@pytest.fixture
def author(fake_guild: FakeGuild) -> FakeMember:
    member = FakeMember(id=424242, name="cirno", guild=fake_guild)
    fake_guild.add_member(member)
    return member


@pytest.fixture
def channel(fake_guild: FakeGuild) -> FakeChannel:
    instance = FakeChannel(id=99, name="general", guild=fake_guild)
    fake_guild.add_channel(instance)
    return instance


@pytest.fixture
def ctx(
    bot: CazzuBot,
    fake_guild: FakeGuild,
    author: FakeMember,
    channel: FakeChannel,
) -> FakeContext:
    return FakeContext(
        bot=bot,
        author=author,
        guild=fake_guild,
        channel=channel,
    )
