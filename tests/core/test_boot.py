"""Boot smoke + persistence — ported from scripts/smoke.py and functest.

Covers: plugin loading, data-layer roundtrip, and data surviving a full
close/reopen of the database. Boots drive the hikari lifecycle handlers
directly (``_on_starting`` / ``_on_stopping``) — no Discord connection.
"""

from __future__ import annotations

from pathlib import Path

import hikari
import pendulum
import pytest

from cazzubot import CazzuBot, Config
from cazzubot.models import FrogTypeEnum
from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db

_UID = 424242

from tests.conftest import _DUMMY_TOKEN  # noqa: E402  (constant, not a fixture)


def _boot_bot(path: str, tmp_plugins: Path) -> CazzuBot:
    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=path,
        ),
        plugins_dir=str(tmp_plugins / "no_plugins"),
    )
    return instance


async def _boot(instance: CazzuBot) -> None:
    await instance._on_starting(  # pyright: ignore[reportPrivateUsage]
        hikari.StartingEvent(app=instance)
    )
    await instance._on_started(  # pyright: ignore[reportPrivateUsage]
        hikari.StartedEvent(app=instance)
    )


async def _shutdown(instance: CazzuBot) -> None:
    await instance._on_stopping(  # pyright: ignore[reportPrivateUsage]
        hikari.StoppingEvent(app=instance)
    )


async def test_boot_loads_plugins_and_commands(
    tmp_path: Path,
) -> None:
    """A real boot with the actual plugin set: schemas, extensions, tasks."""
    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "full.db"),
        ),
        plugins_dir="plugins",
    )
    await _boot(instance)
    try:
        names = {p.name for p in instance.plugins}
        assert {
            "experience",
            "levels",
            "ranks",
            "frogs",
            "mod",
            "poll",
            "counter",
            "dev",
        } <= names
        assert instance.lightbulb.registered_commands
        # every extension registered its commands with the client
        assert instance.lightbulb._extensions  # pyright: ignore[reportPrivateUsage]
    finally:
        await _shutdown(instance)


async def test_sandbox_boot_loads_only_requested_plugins(
    tmp_path: Path,
) -> None:
    """A filtered boot loads the allowlist plus declared dependencies."""
    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "sandbox.db"),
            sandbox_plugins=("frogs",),
        ),
        plugins_dir="plugins",
    )
    await _boot(instance)
    try:
        assert {p.name for p in instance.plugins} == {
            "experience",
            "levels",
            "ranks",
            "frogs",
        }
    finally:
        await _shutdown(instance)


async def test_sandbox_boot_unknown_plugin_aborts(tmp_path: Path) -> None:
    """An unknown plugin name refuses to boot instead of loading nothing."""
    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "sandbox.db"),
            sandbox_plugins=("nope",),
        ),
        plugins_dir="plugins",
    )
    try:
        with pytest.raises(SystemExit) as exc:
            await instance._on_starting(  # pyright: ignore[reportPrivateUsage]
                hikari.StartingEvent(app=instance)
            )
        assert exc.value.code == 1
    finally:
        await _shutdown(instance)


async def test_data_layer_roundtrip(bot: CazzuBot) -> None:
    await bot.scheduler.add("smoke", pendulum.now("UTC"), {"k": "v"})
    assert await bot.scheduler.get("smoke")
    await bot.settings.set("smoke.key", [1, 2, 3])
    assert await bot.settings.get("smoke.key") == [1, 2, 3]


async def test_data_persists_across_reopen(tmp_path: Path) -> None:
    path = str(tmp_path / "persist.db")
    bot1 = _boot_bot(path, tmp_path)
    await _boot(bot1)
    # the empty-plugin boot applies core schemas only; this test exercises
    # plugin tables, so apply the two it touches.
    from plugins.experience import plugin as exp_plugin
    from plugins.frogs import plugin as frog_plugin

    await bot1.db.run_schema(exp_plugin.schema)
    await bot1.db.run_schema(frog_plugin.schema)
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot1.db, _UID)
    await exp_db.add_exp_log(bot1.db, _UID, 80, now)
    await exp_db.sync_with_exp_logs(bot1.db)
    await frog_db.modify_frog(
        bot1.db, _UID, modify=5, frog_type=FrogTypeEnum.FROZEN
    )
    await bot1.settings.set("welcome.message", {"content": "hi {name}"})
    await _shutdown(bot1)

    bot2 = _boot_bot(path, tmp_path)
    await _boot(bot2)
    try:
        member = await exp_db.get_member_exp(bot2.db, _UID)
        assert member is not None and member.lifetime == 80
        assert (
            await frog_db.get_frogs(bot2.db, _UID, FrogTypeEnum.FROZEN)
        ) == 5
        msg = await bot2.settings.get("welcome.message")
        assert msg is not None and msg["content"] == "hi {name}"
    finally:
        await _shutdown(bot2)
