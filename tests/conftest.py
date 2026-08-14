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
    """A booted CazzuBot with plugin schemas but no extensions or hooks."""
    import hikari

    from cazzubot.plugin import discover_plugins

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
    # plugin tables only — the extensions/cogs/hooks are ported plugin by
    # plugin and get their own fixtures; db tests just need the DDL.
    for plugin in discover_plugins("plugins"):
        await instance.db.run_schema(plugin.schema)
    # the asset registry rows (NULL url — offline, like a production
    # boot without a configured asset channel). Species need no seeding:
    # they are defined in code.
    await seed_asset_registry(instance)
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
async def seeded_bot(
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
    await seed_asset_registry(bot)
    return bot


async def seed_asset_registry(bot: CazzuBot) -> None:
    """Register every declared asset with a NULL url (offline tests).

    ``bot.assets.get(member)`` then resolves to None — the same state a
    production boot without a configured asset channel ends up in — while
    unknown members still raise like they would in production.
    """
    from cazzubot.assets import asset_key
    from cazzubot.plugin import discover_plugins

    for plugin in discover_plugins("plugins"):
        decl = plugin.asset_decl
        if decl is None:
            continue
        for asset in decl:
            spec = asset.value
            await bot.db.execute(
                """
				INSERT OR IGNORE INTO asset (key, kind, sha256, path)
				VALUES (?, ?, '', ?)
				""",
                asset_key(asset),
                spec.kind.value,
                f"{plugin.name}/{spec.path}",
            )


async def boot_full_bot(
    tmp_path: Path, *, debug: bool = False
) -> CazzuBot:
    """Boot a real CazzuBot with every plugin loaded, fully offline.

    The ``tests.driver`` harness presses buttons / runs slash commands
    against this bot: real extensions, real lightbulb client (menus,
    modals, command pipeline), real scheduler — with fake cache/rest wired
    in before the lifecycle starts so plugin ``on_load`` hooks never touch
    the network. lightbulb's command-tree sync (the one network call at
    startup) is disabled while keeping the in-memory registration that
    routes interactions.
    """
    import hikari

    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "full.db"),
            debug=debug,
        ),
        plugins_dir="plugins",
    )
    # keep the in-memory command registration, skip the REST sync
    instance.lightbulb.sync_commands = False

    # the harness contract is "every plugin loaded" — force-enable the
    # disabled-by-default mod plugin so its tests and the command-guard
    # sweep see it (the settings schema is applied before the boot hook).
    await instance.db.connect()
    await instance.db.run_schema(instance.settings.schema)
    await instance.settings.set("plugin.enabled.mod", True)
    await instance.db.close()

    cache, rest = FakeCache(), FakeRest()
    guild = FakeGuild(id=2, owner_id=1)
    member = FakeMember(
        id=424242, name="cirno", guild=guild, administrator=True
    )
    channel = FakeChannel(id=99, name="general", guild_id=2)
    cache.add_guild(guild)
    cache.add_member(member)
    cache.add_channel(channel)
    rest.members[(guild.id, member.id)] = member
    seed_bot(instance, cache=cache, rest=rest)
    # owner checks short-circuit without a fetch_application round-trip
    instance.lightbulb._owner_ids = {1}  # pyright: ignore[reportPrivateUsage]

    # drive the lifecycle through the real event manager so the lightbulb
    # client actually starts (the plain bot fixture calls handlers directly
    # and never starts its client)
    await instance.event_manager.dispatch(
        hikari.StartingEvent(app=instance), return_tasks=True
    )
    await instance.event_manager.dispatch(
        hikari.StartedEvent(app=instance), return_tasks=True
    )
    return instance


@pytest.fixture
async def full_bot(tmp_path: Path) -> AsyncGenerator[CazzuBot, None]:
    """A fully-booted offline bot with every plugin loaded (driver tests)."""
    import hikari

    instance = await boot_full_bot(tmp_path)
    yield instance
    await instance._on_stopping(  # pyright: ignore[reportPrivateUsage]
        hikari.StoppingEvent(app=instance)
    )
