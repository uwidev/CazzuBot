"""Mod service (logic) layer — pure decision helpers."""

from __future__ import annotations

import pendulum
import pytest
from discord.ext import commands

from cazzubot.models import ModlogTypeEnum
from plugins.mod.logic import ensure_future, resolve_ban_type


def test_resolve_ban_type() -> None:
    assert (
        resolve_ban_type(pendulum.now("UTC").add(hours=1))
        is ModlogTypeEnum.TEMPBAN
    )
    assert resolve_ban_type(None) is ModlogTypeEnum.BAN


def test_ensure_future_rejects_past() -> None:
    now = pendulum.now("UTC")
    ensure_future(now, now.add(hours=1))  # future: no raise
    with pytest.raises(commands.BadArgument):
        ensure_future(now, now.subtract(hours=1))
