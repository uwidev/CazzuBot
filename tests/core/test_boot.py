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
from cazzubot.models import FrogState, SpeciesKey
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


async def test_plugin_on_load_asset_drift_aborts(tmp_path: Path) -> None:
    """A plugin whose on_load reports asset drift refuses to boot."""
    # a distinct package name: the real ``plugins`` package is already in
    # sys.modules (other tests import it), which would shadow a tmp one
    plugin_dir = tmp_path / "drift_plugins"
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("")
    (plugin_dir / "drifty.py").write_text(
        "from cazzubot import Plugin\n"
        "from cazzubot.assets import AssetError\n"
        "\n"
        "class Drifty(Plugin):\n"
        "    name = 'drifty'\n"
        "\n"
        "    async def on_load(self, _bot):\n"
        "        raise AssetError('boom')\n"
        "\n"
        "plugin = Drifty()\n"
    )
    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "drift.db"),
        ),
        plugins_dir=str(plugin_dir),
    )
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        with pytest.raises(SystemExit) as exc:
            await instance._on_starting(  # pyright: ignore[reportPrivateUsage]
                hikari.StartingEvent(app=instance)
            )
        assert exc.value.code == 1
    finally:
        sys.path.remove(str(tmp_path))
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
    await frog_db.modify_inventory(
        bot1.db, _UID, SpeciesKey.LEAF_FROG, FrogState.FROZEN, 5
    )
    await bot1.settings.set("welcome.message", {"content": "hi {name}"})
    await _shutdown(bot1)

    bot2 = _boot_bot(path, tmp_path)
    await _boot(bot2)
    try:
        member = await exp_db.get_member_exp(bot2.db, _UID)
        assert member is not None and member.lifetime == 80
        assert (
            await frog_db.get_inventory(
                bot2.db, _UID, SpeciesKey.LEAF_FROG, FrogState.FROZEN
            )
            == 5
        )
        msg = await bot2.settings.get("welcome.message")
        assert msg is not None and msg["content"] == "hi {name}"
    finally:
        await _shutdown(bot2)


# -- lifecycle: task-row withdrawal + dependents-aware reload ---------------


async def test_unload_withdraws_scheduler_rows(full_bot: CazzuBot) -> None:
    """Unloading a plugin drops its task rows (projections) — the lifecycle
    replays the deferred undos, so no rows fire into "no handler" later."""
    assert await full_bot.scheduler.get("daily")
    assert "daily" in full_bot.scheduler.handlers

    await full_bot.unload_plugin_by_name("daily")

    assert await full_bot.scheduler.get("daily") == []
    assert "daily" not in full_bot.scheduler.handlers
    assert "daily" not in {p.name for p in full_bot.plugins}


async def test_reload_cascades_to_dependents(full_bot: CazzuBot) -> None:
    """Reloading a provider also reloads its loaded dependents (their
    imports of the provider's modules would otherwise go stale)."""
    affected = full_bot.affected_by_unload("experience")
    assert "experience" in affected
    assert "frogs" in affected  # frogs depends on experience
    assert "daily" in affected  # daily depends on (experience, frogs)

    plugin = await full_bot.reload_plugin("experience")

    assert plugin.name == "experience"
    names = {p.name for p in full_bot.plugins}
    for name in affected:
        assert name in names, f"{name} missing after cascade reload"


async def test_unload_plugin_by_name_cascades(full_bot: CazzuBot) -> None:
    """Unloading a provider takes its loaded dependents with it."""
    affected = full_bot.affected_by_unload("experience")
    assert len(affected) > 1

    await full_bot.unload_plugin_by_name("experience")

    names = {p.name for p in full_bot.plugins}
    for name in affected:
        assert name not in names, f"{name} still loaded after cascade"
