"""Welcome service layer — pure welcome decisions, no discord objects.

The controller (extension) reads settings, resolves the channel/role and performs
the side effects; whether a member update should trigger a welcome is a pure
function of plain values.
"""

from __future__ import annotations

from cazzubot.models import WelcomeModeEnum


def should_welcome(
    mode: WelcomeModeEnum,
    *,
    before_pending: bool,
    after_pending: bool,
    before_role_ids: set[int],
    after_role_ids: set[int],
    monitor_rid: int | None,
    member_id: int,
    last_welcomed_id: int | None,
) -> bool:
    """Decide whether a member update should trigger the welcome.

    - ``pending`` mode: onboarding flag cleared and this member wasn't just
      welcomed (the double-welcome race guard).
    - ``role`` mode: the monitored role was gained. Uses set membership
      (deterministic); the original ``set.pop()`` check was order-dependent
      when several roles were gained at once.
    """
    if mode is WelcomeModeEnum.PENDING:
        return (
            before_pending != after_pending
            and member_id != last_welcomed_id
        )
    # ROLE is the only other value
    gained = after_role_ids - before_role_ids
    return (
        bool(gained) and monitor_rid is not None and monitor_rid in gained
    )
