"""Shared fixtures: a real booted bot against a temp sqlite database.

Same pattern as before the hikari swap, minus the Discord connection: build
a ``CazzuBot`` with a fake (well-formed) token, then drive the lifecycle
handlers directly — ``_on_starting`` for db/schema/plugin load/scheduler,
``_on_started`` for the ready gate. The bot boots with an **empty** plugins
dir so core tests don't need (unported) plugin cogs; plugin tests seed
their own fakes via ``tests.fakes.seed_bot``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from cazzubot import CazzuBot, Config
from cazzubot.db import Database
from tests.fakes import (
    FakeCache,
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeMember,
    FakeRest,
    seed_bot,
)

# hikari validates the token's JWT-ish shape at construction time.
_DUMMY_TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Ng.OTg3NjU0MzIxMDEyMzQ1Ng.dummy"


@pytest.fixture
async def db(tmp_path: Path) -> AsyncGenerator[Database, None]:
    """A bare connected Database (repository-layer tests)."""
    instance = Database(str(tmp_path / "data.db"))
    await instance.connect()
    yield instance
    await instance.close()


@pytest.fixture
async def bot(tmp_path: Path) -> AsyncGenerator[CazzuBot, None]:
    """A booted CazzuBot with no plugins and no Discord connection."""
    import hikari

    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "test.db"),
        ),
        plugins_dir=str(tmp_path / "no_plugins"),
    )
    await instance._on_starting(  # pyright: ignore[reportPrivateUsage]
        hikari.StartingEvent(app=instance)
    )
    await instance._on_started(  # pyright: ignore[reportPrivateUsage]
        hikari.StartedEvent(app=instance)
    )
    yield instance
    await instance._on_stopping(  # pyright: ignore[reportPrivateUsage]
        hikari.StoppingEvent(app=instance)
    )


@pytest.fixture
def fake_cache() -> FakeCache:
    return FakeCache()


@pytest.fixture
def fake_rest() -> FakeRest:
    return FakeRest()


@pytest.fixture
def fake_guild() -> FakeGuild:
    return FakeGuild(id=2, owner_id=1)


@pytest.fixture
def author(fake_guild: FakeGuild) -> FakeMember:
    return FakeMember(id=424242, name="cirno", guild=fake_guild)


@pytest.fixture
def channel(fake_guild: FakeGuild) -> FakeChannel:
    return FakeChannel(id=99, name="general", guild_id=fake_guild.id)


@pytest.fixture
def ctx(
    bot: CazzuBot,
    fake_guild: FakeGuild,
    author: FakeMember,
    channel: FakeChannel,
) -> FakeContext:
    return FakeContext(
        bot=bot,
        member=author,
        guild=fake_guild,
        channel=channel,
    )


@pytest.fixture
def seeded_bot(
    bot: CazzuBot,
    fake_cache: FakeCache,
    fake_rest: FakeRest,
    fake_guild: FakeGuild,
    author: FakeMember,
    channel: FakeChannel,
) -> CazzuBot:
    """A booted bot with cache/rest fakes pre-seeded and wired to it."""
    fake_cache.add_guild(fake_guild)
    fake_cache.add_member(author)
    fake_cache.add_channel(channel)
    fake_rest.members[(fake_guild.id, author.id)] = author
    seed_bot(bot, cache=fake_cache, rest=fake_rest)
    return bot
