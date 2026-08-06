"""Data-layer + logic functional tests (no Discord connection needed).

Exercises the exp pipeline, level math, rank thresholds, scheduler dispatch,
frog economy, modlog, templates and time parsing against a temp sqlite DB.

Usage: .venv/bin/python scripts/functest.py
"""

import asyncio
import json
import os
import sys
import tempfile
from typing import Any

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import pendulum  # noqa: E402

from cazzubot import CazzuBot, Config  # noqa: E402
from cazzubot import levels, timeparse  # noqa: E402
from cazzubot.models import FrogTypeEnum, ModlogTypeEnum  # noqa: E402
from cazzubot.utils import OldNew  # noqa: E402
from cazzubot.window import (  # noqa: E402
    command_window,
    window_info,
    window_warn,
    windowed,
)

from plugins.experience import db as exp_db  # noqa: E402
from plugins.frogs import db as frog_db  # noqa: E402
from plugins.ranks import db as ranks_db  # noqa: E402

passed = 0


def ok(name: str) -> None:
    global passed
    passed += 1
    print(f"  ✓ {name}")


async def main() -> None:
    path = os.path.join(tempfile.mkdtemp(), "functest.db")
    bot = CazzuBot(
        Config(token="fake", owner_id=1, guild_id=2, db_path=path)
    )

    async def _ready() -> None:
        pass

    bot.wait_until_ready = _ready  # type: ignore[method-assign]
    await bot.setup_hook()

    # -- experience pipeline ------------------------------------------------
    print("experience:")
    uid = 424242
    await exp_db.add_member_exp(bot.db, uid)
    now = pendulum.now("UTC")
    await exp_db.add_exp_log(bot.db, uid, 50, now)
    await exp_db.add_exp_log(bot.db, uid, 30, now.add(seconds=1))
    await exp_db.add_exp_log(bot.db, 777, 100, now)
    member = await exp_db.get_member_exp(bot.db, uid)
    assert member is not None and member["lifetime"] == 0
    seasonal = await exp_db.seasonal_exp(
        bot.db, uid, now.year, (now.month - 1) // 3
    )
    assert seasonal == 80, seasonal
    ranked = await exp_db.seasonal_ranked(
        bot.db, now.year, (now.month - 1) // 3
    )
    assert ranked[0] == (1, 777, 100) and ranked[1][0] == 2, ranked
    await exp_db.sync_with_exp_logs(bot.db)
    member = await exp_db.get_member_exp(bot.db, uid)
    assert member is not None and member["lifetime"] == 80
    await exp_db.update_member_exp(
        bot.db,
        uid,
        lifetime=80,
        msg_cnt=5,
        cdr=now.add(seconds=15),
    )
    member = await exp_db.get_member_exp(bot.db, uid)
    assert member is not None and member["msg_cnt"] == 5
    ok("exp award/log/sync/ranked roundtrip")

    # -- level math ---------------------------------------------------------
    assert levels.level_from_exp(0) == 0
    assert levels.level_from_exp(10_000) > 0
    assert levels.exp_to_level_cum(5) > 0
    assert levels.exp_to_level_cum(10) > levels.exp_to_level_cum(5)
    ok(f"level math (lv@10000={levels.level_from_exp(10_000)})")

    # -- ranks --------------------------------------------------------------

    await ranks_db.add(bot.db, 111, 5)
    await ranks_db.add(bot.db, 222, 10)
    await ranks_db.add(bot.db, 333, 20)
    thresholds = await ranks_db.get(bot.db)
    assert [t["threshold"] for t in thresholds] == [5, 10, 20], thresholds
    rid, idx = ranks_db.calc_min_rank(thresholds, 12)
    assert rid == 222 and idx == 1, (rid, idx)
    rid_none, _ = ranks_db.calc_min_rank(thresholds, 2)
    assert rid_none is None
    from plugins.ranks.logic import rank_difference

    diffs = rank_difference(OldNew(6, 12), thresholds)
    assert diffs[0].old == 111 and diffs[0].new == 222, diffs
    assert diffs[1].old == 0 and diffs[1].new == 1, diffs
    ok("rank thresholds + rank_difference")

    # -- scheduler ----------------------------------------------------------
    fired: list[dict[str, Any]] = []

    async def handler(_bot: CazzuBot, payload: dict[str, Any]) -> None:
        fired.append(payload)

    bot.scheduler.register("test", handler)
    await bot.scheduler.add(
        "test", pendulum.now("UTC").subtract(seconds=1), {"x": 1}
    )
    await bot.scheduler._tick()  # pyright: ignore[reportPrivateUsage]  # pump
    assert fired == [{"x": 1}]
    assert await bot.scheduler.get("test") == []
    ok("scheduler dispatch + row cleanup")

    # failing handler keeps its row for retry (e.g. mute expiry)
    fired.clear()

    async def bad_handler(
        _bot: CazzuBot, _payload: dict[str, Any]
    ) -> None:
        raise RuntimeError("transient")

    bot.scheduler.register("flaky", bad_handler)
    await bot.scheduler.add(
        "flaky", pendulum.now("UTC").subtract(seconds=1)
    )
    await bot.scheduler._tick()  # pyright: ignore[reportPrivateUsage]  # pump
    rows = await bot.scheduler.get("flaky")
    assert len(rows) == 1, rows  # kept, pushed 30s into the future
    ok("scheduler keeps failed tasks (retry)")

    # -- frogs --------------------------------------------------------------
    await frog_db.modify_frog(bot.db, uid, modify=3)
    await frog_db.modify_frog(
        bot.db, uid, modify=2, frog_type=FrogTypeEnum.FROZEN
    )
    assert await frog_db.get_frogs(bot.db, uid) == 3
    await frog_db.modify_capture(bot.db, uid, modify=5)
    await frog_db.add_capture_log(bot.db, uid, now, waited_for=1.5)
    f_ranked = await frog_db.seasonal_ranked(
        bot.db, now.year, (now.month - 1) // 3
    )
    assert f_ranked[0][2] == 1, f_ranked
    await frog_db.freeze_frogs(bot.db)
    assert await frog_db.get_frogs(bot.db, uid) == 0  # normal drained
    assert await frog_db.get_frogs(bot.db, uid, FrogTypeEnum.FROZEN) == 5
    ok("frog inventory / freeze / capture log")

    # -- modlog -------------------------------------------------------------
    from plugins.mod import add_log

    await add_log(
        bot.db,
        uid,
        ModlogTypeEnum.MUTE,
        now,
        expires_on=now.add(hours=1),
        reason="test",
    )
    row = await bot.db.fetchone("SELECT * FROM modlog")
    assert row is not None
    assert row["log_type"] == "mute" and row["status"] == "active"
    ok("modlog insert")

    # -- settings -----------------------------------------------------------
    await bot.settings.set("welcome.message", {"content": "hi {name}"})
    assert (await bot.settings.get("welcome.message"))[
        "content"
    ] == "hi {name}"
    ok("settings roundtrip (json)")

    # -- templates ----------------------------------------------------------
    from cazzubot import templates
    from plugins.levels.logic import formatter

    class FakeAvatar:
        url = "https://example.com/avatar.png"

    class FakeMember:
        display_avatar = FakeAvatar()
        display_name = "cirno"
        mention = "<@123>"
        id = 123

    msg: dict[str, Any] = {
        "content": "hi {mention}",
        "embed": {"title": "t", "description": "{name}", "fields": []},
    }
    valid = templates.verify(
        json.dumps(msg), formatter, member=FakeMember()
    )
    assert valid["embed"]["description"] == "{name}"
    bad = '{"attachments": [1]}'
    try:
        templates.verify(bad)
        raise AssertionError("should have rejected attachments")
    except Exception:
        pass
    ok("template verify accepts/rejects")

    # -- timeparse ----------------------------------------------------------
    dt = timeparse.normalize_time_str("2 hours from now")
    assert dt > pendulum.now("UTC")
    dur = timeparse.parse_duration("1d 30m")
    assert dur.in_seconds() == 86400 + 1800
    try:
        timeparse.parse_duration("nonsense")
        raise AssertionError("should have raised")
    except timeparse.InvalidTimeError:
        pass
    ok("timeparse duration + natural time")

    # -- runtime pipeline imports (exp on_message deps) ----------------------
    from plugins.levels.logic import handle_level_up  # noqa: E402
    from plugins.ranks.logic import handle_ranks, is_ranked_up  # noqa: E402
    from plugins.frogs.factory import on_frog_due  # noqa: E402
    from plugins.mod import on_modlog_due  # noqa: E402
    from plugins.counter import on_counter_expire  # noqa: E402

    # referenced so the import graph is exercised at runtime (typos surface
    # here rather than on the first real message)
    _pipeline = (
        handle_level_up,
        handle_ranks,
        is_ranked_up,
        on_frog_due,
        on_modlog_due,
        on_counter_expire,
    )

    ok("on_message/scheduler pipeline imports resolve")

    # -- persistence: close, reopen, verify data survived --------------------
    db_path = bot.config.db_path
    await bot.close()

    bot2 = CazzuBot(
        Config(token="fake", owner_id=1, guild_id=2, db_path=db_path)
    )

    async def _ready2() -> None:
        pass

    bot2.wait_until_ready = _ready2  # type: ignore[method-assign]
    await bot2.setup_hook()
    try:
        member = await exp_db.get_member_exp(bot2.db, uid)
        assert member is not None and member["lifetime"] == 80
        assert (
            await frog_db.get_frogs(bot2.db, uid, FrogTypeEnum.FROZEN)
        ) == 5
        msg = await bot2.settings.get("welcome.message")
        assert msg is not None and msg["content"] == "hi {name}"
    finally:
        await bot2.close()
    ok("data persists across database reopen")

    # -- window: buffered internal-state reporting --------------------------

    class FakeSendCtx:
        def __init__(self, interaction: Any = None) -> None:
            self.interaction = interaction
            self.sent: list[tuple[str | None, dict[str, Any]]] = []

        async def send(
            self, content: str | None = None, **kwargs: Any
        ) -> None:
            self.sent.append((content, kwargs))

    ctx_fake = FakeSendCtx()
    async with command_window(ctx_fake) as window:
        window.debug("dbg")
        window.info("fetching")
        window.success("done")
        window.warn("slow")
        window.error("boom")
    assert len(ctx_fake.sent) == 1  # one message, not one per line
    text, kwargs = ctx_fake.sent[0]
    assert text is not None
    assert text.splitlines()[2] == "✓ done"
    assert text.splitlines()[3] == "⚠︎ slow"
    assert text.splitlines()[4] == "✖ boom"
    assert kwargs == {"ephemeral": True}
    ok("window buffers levels into one ephemeral message")

    ctx_fake.sent.clear()
    async with command_window(ctx_fake) as window:
        pass
    assert ctx_fake.sent == []
    ok("window empty flush is a no-op")

    ctx_fake.sent.clear()
    try:
        async with command_window(ctx_fake) as window:
            window.info("partial")
            raise RuntimeError("kaboom")
        raise AssertionError("should have raised")
    except RuntimeError:
        pass
    text, _ = ctx_fake.sent[0]
    assert text is not None
    assert "partial" in text and "✖ RuntimeError: kaboom" in text
    ok("window flushes state + error on exception")

    ctx_fake.sent.clear()
    async with command_window(ctx_fake) as window:
        window.info("a|b")
        await window.flush(monospace=True)
    text, _ = ctx_fake.sent[0]
    assert text is not None
    assert text == "```\na|b\n```"
    ok("window monospace flush wraps in code block")

    @windowed
    async def _windowed_cmd(_self: object, ctx: Any, val: int) -> int:
        ctx.window.success(f"val={val}")
        return val

    ctx_fake.sent.clear()
    assert await _windowed_cmd(None, ctx_fake, 3) == 3
    assert ctx_fake.sent == [("✓ val=3", {"ephemeral": True})]
    ok("windowed decorator exposes ctx.window and auto-flushes")

    ctx_fake.sent.clear()
    await window_info(ctx_fake, "hi")
    await window_warn(ctx_fake, "careful")
    assert len(ctx_fake.sent) == 2
    assert ctx_fake.sent[0][0] == "hi"
    assert ctx_fake.sent[1][0] == "⚠︎ careful"
    ok("window one-off helpers send single lines")

    print(f"\nALL {passed} FUNCTIONAL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
