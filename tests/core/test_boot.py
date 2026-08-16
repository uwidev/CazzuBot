"""Boot smoke + persistence — ported from scripts/smoke.py and functest.

Covers: plugin loading, data-layer roundtrip, and data surviving a full
close/reopen of the database. Boots drive the hikari lifecycle handlers
directly (``_on_starting`` / ``_on_stopping``) — no Discord connection.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import hikari
import pendulum
import pytest

from cazzubot import CazzuBot, Config
from cazzubot.models import FrogState, SpeciesKey
from cazzubot.plugin import Plugin
from cazzubot.scheduler import TaskPolicy
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
            "poll",
            "counter",
            "dev",
        } <= names
        # mod ships disabled (incomplete; moderation handled elsewhere) —
        # it must not load unless explicitly enabled
        assert "mod" not in names
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


async def test_scheduled_entry_carries_policy(
    bot: CazzuBot,
) -> None:
    """A ``(handler, TaskPolicy)`` scheduled entry wires the policy in.

    ``Plugin.scheduled`` values may be a bare handler (default policy) or
    a (handler, policy) pair; loading must land the policy in
    ``scheduler.policies`` and unloading must withdraw it with the rest
    of the plugin's deferred effects.
    """
    policy = TaskPolicy(stale_after=timedelta(hours=1))

    async def handler(_bot: CazzuBot, _payload: dict[str, Any]) -> None:
        return None

    class WithPolicy(Plugin):
        name = "withpolicy"
        scheduled = {"wp": (handler, policy)}

    class Plain(Plugin):
        name = "plain"
        scheduled = {"pl": handler}

    await bot.load_plugin(WithPolicy(), run_hooks=False)
    await bot.load_plugin(Plain(), run_hooks=False)
    try:
        assert bot.scheduler.handlers["wp"] is handler
        assert bot.scheduler.policies["wp"] is policy
        # a bare entry registers under the default policy, not a custom one
        assert bot.scheduler.handlers["pl"] is handler
        assert "pl" not in bot.scheduler.policies
    finally:
        await bot.unload_plugin_by_name("withpolicy")
        await bot.unload_plugin_by_name("plain")
    # unload withdraws the policy with the handler
    assert "wp" not in bot.scheduler.policies
    assert "pl" not in bot.scheduler.handlers


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
    assert await full_bot.scheduler.get("quarterly")  # armed by frogs
    assert "quarterly" in full_bot.scheduler.handlers

    await full_bot.unload_plugin_by_name("frogs")

    assert await full_bot.scheduler.get("quarterly") == []
    assert "quarterly" not in full_bot.scheduler.handlers
    assert "frogs" not in {p.name for p in full_bot.plugins}


async def test_reload_cascades_to_dependents(full_bot: CazzuBot) -> None:
    """Reloading a provider also reloads its loaded dependents (their
    imports of the provider's modules would otherwise go stale)."""
    affected = full_bot.affected_by_unload("experience")
    assert "experience" in affected
    assert "frogs" in affected  # frogs depends on experience
    assert "levels" in affected and "ranks" in affected

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


# -- plugin enable/disable ---------------------------------------------------


async def _preset_setting(
    instance: CazzuBot, key: str, value: object
) -> None:
    """Write a settings row before the boot hook runs (schema applied)."""
    await instance.db.connect()
    await instance.db.run_schema(instance.settings.schema)
    await instance.settings.set(key, value)
    await instance.db.close()


async def test_boot_skips_setting_disabled_plugin(tmp_path: Path) -> None:
    """A plugin disabled via settings does not load at boot."""
    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "disabled.db"),
        ),
        plugins_dir="plugins",
    )
    await _preset_setting(instance, "plugin.enabled.counter", False)
    await _boot(instance)
    try:
        names = {p.name for p in instance.plugins}
        assert "counter" not in names
        assert "experience" in names
    finally:
        await _shutdown(instance)


async def test_boot_cascades_to_dependents_of_disabled(
    tmp_path: Path,
) -> None:
    """Disabling a provider skips its dependents at boot too."""
    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "cascade.db"),
        ),
        plugins_dir="plugins",
    )
    # ranks is a dependency of experience/levels/frogs
    await _preset_setting(instance, "plugin.enabled.ranks", False)
    await _boot(instance)
    try:
        names = {p.name for p in instance.plugins}
        assert "ranks" not in names
        assert "experience" not in names
        assert "levels" not in names
        assert "frogs" not in names
        assert "poll" in names  # independent plugin still loads
    finally:
        await _shutdown(instance)


async def test_sandbox_requesting_disabled_plugin_aborts(
    tmp_path: Path,
) -> None:
    """An explicitly requested-but-disabled plugin refuses to boot."""
    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "sandbox.db"),
            sandbox_plugins=("counter",),
        ),
        plugins_dir="plugins",
    )
    await _preset_setting(instance, "plugin.enabled.counter", False)
    try:
        with pytest.raises(SystemExit) as exc:
            await instance._on_starting(  # pyright: ignore[reportPrivateUsage]
                hikari.StartingEvent(app=instance)
            )
        assert exc.value.code == 1
    finally:
        await _shutdown(instance)


async def test_enable_plugin_loads_and_persists(
    full_bot: CazzuBot,
) -> None:
    """Runtime enable loads the plugin and persists the flag."""
    # mod ships disabled and is not loaded by the harness-agnostic default
    await full_bot.disable_plugin("counter")
    assert "counter" not in {p.name for p in full_bot.plugins}

    loaded = await full_bot.enable_plugin("counter")

    assert loaded == ["counter"]
    assert "counter" in {p.name for p in full_bot.plugins}
    assert await full_bot.settings.get("plugin.enabled.counter") is True


async def test_disable_plugin_unloads_cascade_and_persists(
    full_bot: CazzuBot,
) -> None:
    """Runtime disable unloads the plugin and its dependents, persists."""
    unloaded = await full_bot.disable_plugin("experience")

    assert "experience" in unloaded
    assert "frogs" in unloaded  # depends on experience
    names = {p.name for p in full_bot.plugins}
    for name in unloaded:
        assert name not in names
    assert (
        await full_bot.settings.get("plugin.enabled.experience") is False
    )


async def test_disabled_state_survives_restart(tmp_path: Path) -> None:
    """A runtime disable is still honored by the next boot."""
    path = str(tmp_path / "persist-disabled.db")
    bot1 = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=path,
        ),
        plugins_dir="plugins",
    )
    await _boot(bot1)
    await bot1.disable_plugin("counter")
    await _shutdown(bot1)

    bot2 = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=path,
        ),
        plugins_dir="plugins",
    )
    await _boot(bot2)
    try:
        assert "counter" not in {p.name for p in bot2.plugins}
        assert "experience" in {p.name for p in bot2.plugins}
    finally:
        await _shutdown(bot2)
