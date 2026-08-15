"""Mod state-backed scheduling — task rows are projections of the modlog.

The source of truth is ``modlog`` (status='active' + expires_on); the
``modlog`` scheduler rows are rebuilt on load and applied immediately when
overdue, so an unload or restart never loses a mute/tempban expiry.
"""

from __future__ import annotations

from typing import Any, cast

import pendulum

from cazzubot import CazzuBot
from cazzubot.models import ModlogStatusEnum, ModlogTypeEnum
from plugins.mod import db as mod_db
from plugins.mod.extension import on_modlog_due
from tests.fakes import FakeMember, FakeRole, rest_of

_MUTE_ROLE_ID = 4444


def _mute_role() -> FakeRole:
    return FakeRole(id=_MUTE_ROLE_ID, name="Muted")


async def _seed_expiry(
    bot: CazzuBot,
    *,
    uid: int,
    log_type: ModlogTypeEnum,
    expires_on: pendulum.DateTime,
) -> int:
    return await mod_db.add_log(
        bot.db,
        uid,
        log_type,
        pendulum.now("UTC"),
        expires_on=expires_on,
        reason="test",
    )


async def test_on_load_rearms_pending_expiries(full_bot: CazzuBot) -> None:
    """A future ACTIVE modlog row becomes a scheduler row again on load."""
    log_id = await _seed_expiry(
        full_bot,
        uid=777,
        log_type=ModlogTypeEnum.MUTE,
        expires_on=pendulum.now("UTC").add(hours=2),
    )
    # drop whatever on_load armed before the seed, then reload to re-scan
    await full_bot.scheduler.drop_tag("modlog")
    await full_bot.reload_plugin("mod")

    tasks = await full_bot.scheduler.get("modlog")
    assert len(tasks) == 1
    assert tasks[0].payload["uid"] == 777
    assert tasks[0].payload["log_id"] == log_id
    assert tasks[0].payload["retry"] is True


async def test_on_load_applies_overdue_expiry(full_bot: CazzuBot) -> None:
    """An overdue ACTIVE row is applied immediately (catch-up), and the
    row is marked resolved so it is never re-applied."""
    await full_bot.settings.set("mod.mute_role", _MUTE_ROLE_ID)
    cast(Any, full_bot.cache).add_role(_mute_role())
    member = FakeMember(id=777, name="muted", roles=[_mute_role()])
    member.guild_id = 2
    cast(Any, full_bot.cache).add_member(member)
    rest_of(full_bot).members[(2, member.id)] = member
    log_id = await _seed_expiry(
        full_bot,
        uid=member.id,
        log_type=ModlogTypeEnum.MUTE,
        expires_on=pendulum.now("UTC").subtract(hours=1),
    )

    await full_bot.reload_plugin("mod")

    assert rest_of(full_bot).removed_roles == [
        (member.id, _MUTE_ROLE_ID, "Mute expired.")
    ]
    row = await full_bot.db.fetchone(
        "SELECT status FROM modlog WHERE id = ?", log_id
    )
    assert (
        row is not None
        and row["status"] == ModlogStatusEnum.PARDONED.value
    )
    # no future task is armed for the resolved row
    assert await full_bot.scheduler.get("modlog") == []


async def test_expiry_marks_its_row_resolved(full_bot: CazzuBot) -> None:
    """Firing an expiry flips the referenced modlog row to pardon."""
    log_id = await _seed_expiry(
        full_bot,
        uid=999,
        log_type=ModlogTypeEnum.TEMPBAN,
        expires_on=pendulum.now("UTC").add(hours=1),
    )

    await on_modlog_due(
        full_bot,
        {
            "uid": 999,
            "log_type": "tempban",
            "log_id": log_id,
            "retry": True,
        },
    )

    row = await full_bot.db.fetchone(
        "SELECT status FROM modlog WHERE id = ?", log_id
    )
    assert (
        row is not None
        and row["status"] == ModlogStatusEnum.PARDONED.value
    )
