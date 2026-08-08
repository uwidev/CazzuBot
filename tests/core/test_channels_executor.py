"""Channels executor snapshot helpers — hikari-shaped channel objects."""

from __future__ import annotations

import datetime
from types import SimpleNamespace

from cazzubot.channels import executor


def _channel(**kw: object) -> SimpleNamespace:
    """A minimal hikari-channel-like object (GUILD_TEXT by default)."""
    defaults: dict[str, object] = {
        "id": 1,
        "name": "general",
        "type": SimpleNamespace(name="GUILD_TEXT"),
        "parent_id": None,
        "position": 0,
        "is_nsfw": False,
        "rate_limit_per_user": None,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_seconds_helper() -> None:
    assert executor._seconds(datetime.timedelta(seconds=5)) == 5
    assert executor._seconds(datetime.timedelta(seconds=120.7)) == 120
    assert executor._seconds(7) == 7
    assert executor._seconds(None) == 0
    assert executor._seconds(0) == 0


def test_snapshot_slowmode_hikari_timedelta() -> None:
    """hikari exposes rate limits as timedeltas — snapshot in seconds."""
    ch = _channel(rate_limit_per_user=datetime.timedelta(seconds=5))
    snap = executor.snapshot_channels([ch])[0]
    assert snap["slowmode"] == 5
    assert snap["kind"] == "text"
    assert snap.get("unsupported") is None


def test_snapshot_slowmode_forum_thread_delta() -> None:
    ch = _channel(
        type=SimpleNamespace(name="GUILD_FORUM"),
        name="forum",
        default_thread_rate_limit_per_user=datetime.timedelta(
            seconds=3600
        ),
    )
    snap = executor.snapshot_channels([ch])[0]
    assert snap["kind"] == "forum"
    assert snap["slowmode"] == 3600


def test_snapshot_unsupported_kind() -> None:
    ch = _channel(
        type=SimpleNamespace(name="GUILD_CATEGORY"), name="Games"
    )
    snap = executor.snapshot_channels([ch])[0]
    assert snap["kind"] == "category"
