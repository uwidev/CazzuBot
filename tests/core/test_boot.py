"""Boot smoke + persistence — ported from scripts/smoke.py and functest.

Covers: plugin loading, command tree wiring, data-layer roundtrip, and data
surviving a full close/reopen of the database.
"""

from __future__ import annotations

from pathlib import Path

import pendulum

from cazzubot import CazzuBot, Config
from cazzubot.models import FrogTypeEnum
from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db

_UID = 424242


def _boot_bot(path: str) -> CazzuBot:
    instance = CazzuBot(
        Config(token="fake", owner_id=1, guild_id=2, db_path=path)
    )

    async def _ready() -> None:
        pass

    instance.wait_until_ready = _ready  # type: ignore[method-assign]
    return instance


async def test_boot_loads_plugins_and_commands(bot: CazzuBot) -> None:
    names = {p.name for p in bot.plugins}
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
    assert len(bot.commands) > 0
    assert bot.tree.get_commands()  # app commands registered


async def test_data_layer_roundtrip(bot: CazzuBot) -> None:
    await bot.scheduler.add("smoke", pendulum.now("UTC"), {"k": "v"})
    assert await bot.scheduler.get("smoke")
    await bot.settings.set("smoke.key", [1, 2, 3])
    assert await bot.settings.get("smoke.key") == [1, 2, 3]


async def test_data_persists_across_reopen(tmp_path: Path) -> None:
    path = str(tmp_path / "persist.db")
    bot1 = _boot_bot(path)
    await bot1.setup_hook()
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot1.db, _UID)
    await exp_db.add_exp_log(bot1.db, _UID, 80, now)
    await exp_db.sync_with_exp_logs(bot1.db)
    await frog_db.modify_frog(
        bot1.db, _UID, modify=5, frog_type=FrogTypeEnum.FROZEN
    )
    await bot1.settings.set("welcome.message", {"content": "hi {name}"})
    await bot1.close()

    bot2 = _boot_bot(path)
    await bot2.setup_hook()
    try:
        member = await exp_db.get_member_exp(bot2.db, _UID)
        assert member is not None and member.lifetime == 80
        assert (
            await frog_db.get_frogs(bot2.db, _UID, FrogTypeEnum.FROZEN)
        ) == 5
        msg = await bot2.settings.get("welcome.message")
        assert msg is not None and msg["content"] == "hi {name}"
    finally:
        await bot2.close()
