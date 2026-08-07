"""Welcome service (logic) layer — pure decision tests."""

from __future__ import annotations

from cazzubot.models import WelcomeModeEnum
from plugins.welcome.logic import should_welcome


def _decide(
    mode: WelcomeModeEnum,
    *,
    before_pending: bool = True,
    after_pending: bool = False,
    before_roles: set[int] | None = None,
    after_roles: set[int] | None = None,
    monitor_rid: int | None = None,
    member_id: int = 1,
    last_welcomed_id: int | None = None,
) -> bool:
    return should_welcome(
        mode,
        before_pending=before_pending,
        after_pending=after_pending,
        before_role_ids=before_roles or set(),
        after_role_ids=after_roles or set(),
        monitor_rid=monitor_rid,
        member_id=member_id,
        last_welcomed_id=last_welcomed_id,
    )


def test_pending_mode_rules() -> None:
    assert _decide(WelcomeModeEnum.PENDING) is True  # flag cleared
    assert _decide(WelcomeModeEnum.PENDING, after_pending=True) is False
    assert _decide(WelcomeModeEnum.PENDING, last_welcomed_id=1) is False


def test_role_mode_rules() -> None:
    assert (
        _decide(
            WelcomeModeEnum.ROLE,
            after_roles={10},
            monitor_rid=10,
        )
        is True
    )
    assert (
        _decide(
            WelcomeModeEnum.ROLE,
            after_roles={11},
            monitor_rid=10,
        )
        is False
    )
    assert _decide(WelcomeModeEnum.ROLE, monitor_rid=10) is False
