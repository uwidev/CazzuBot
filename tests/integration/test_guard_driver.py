"""Guard hooks through the real pipeline (offline driver).

``default_member_permissions`` hides commands from the client; the hooks
are the server-side backstop that must block execution regardless of
what the client shows. These tests run the real lightbulb CHECKS step
for the previously-unguarded mutating commands, plus regressions for
the existing admin gates.
"""

from __future__ import annotations

from cazzubot.bot import CazzuBot
from tests.driver import run_slash


async def test_counter_create_blocked_for_regular_member(
    full_bot: CazzuBot,
) -> None:
    result = await run_slash(
        full_bot, "counter create", user_id=424242, member_permissions=0
    )
    assert not result.responded
    assert result.exceptions == []
    assert await full_bot.db.fetchval("SELECT COUNT(*) FROM counter") == 0


async def test_counter_create_allowed_for_admin(
    full_bot: CazzuBot,
) -> None:
    result = await run_slash(
        full_bot, "counter create", user_id=1, username="owner"
    )
    assert result.exceptions == []
    assert result.responded
    assert await full_bot.db.fetchval("SELECT COUNT(*) FROM counter") == 1


async def test_register_inktober_blocked_for_regular_member(
    full_bot: CazzuBot,
) -> None:
    result = await run_slash(
        full_bot, "register_inktober", user_id=424242, member_permissions=0
    )
    assert not result.responded
    assert result.exceptions == []
    assert await full_bot.settings.get("inktober.cid") is None


async def test_register_inktober_allowed_for_admin(
    full_bot: CazzuBot,
) -> None:
    result = await run_slash(
        full_bot, "register_inktober", user_id=1, username="owner"
    )
    assert result.exceptions == []
    assert result.responded
    assert await full_bot.settings.get("inktober.cid") == 99


async def test_existing_admin_gates_hold(full_bot: CazzuBot) -> None:
    """Regression: frog register / level set stay blocked for non-admins."""
    frog = await run_slash(
        full_bot,
        "frog register",
        options={"interval": "1h"},
        user_id=424242,
        member_permissions=0,
    )
    assert not frog.responded
    assert frog.exceptions == []

    level = await run_slash(
        full_bot,
        "level set",
        options={"message": "{}"},
        user_id=424242,
        member_permissions=0,
    )
    assert not level.responded
    assert level.exceptions == []
    assert await full_bot.settings.get("level.message") is None
