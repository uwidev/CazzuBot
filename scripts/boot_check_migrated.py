#!/bin/env python
"""Boot the real bot stack against the migrated database (no Discord).

Constructs ``CazzuBot`` with ``db_path=data/cazzubot.db``, patches
``wait_until_ready`` (as ``scripts/smoke.py`` does), runs ``setup_hook`` so
every plugin loads, schema applies, scheduler handlers register, and the
``on_load`` hooks run — exactly what happens at a real boot, minus the
gateway. Then asserts the expected first-boot effects on migrated data:

- quarterly catch-up freeze ran iff ``quarterly.last_quarterly`` is stale
- daily reset did NOT force (last_daily is today)
- frog spawn tasks queued to match ``frog_spawn`` x enabled state
- key read paths work: lifetime/seasonal rankings, rank thresholds,
  settings, exp->level math

Run this against a freshly migrated DB before the real first boot. Running
it against a live bot's DB re-runs boot hooks (scheduler, spawn queueing)
and some checks become state-dependent — balances must not change unless a
freeze is actually due.

Usage: .venv/bin/python scripts/boot_check_migrated.py
"""

import asyncio
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

import pendulum  # noqa: E402

from cazzubot import CazzuBot, Config  # noqa: E402
from cazzubot import levels  # noqa: E402
from cazzubot.models import WindowEnum  # noqa: E402
from cazzubot.settings import Settings  # noqa: E402

from plugins.experience import db as exp_db  # noqa: E402
from plugins.ranks import db as ranks_db  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "data" / "cazzubot.db"

FAILS: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    status = "ok  " if cond else "FAIL"
    if not cond:
        FAILS.append(label)
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))


def snapshot() -> dict:
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT uid, normal, frozen, capture, msg_cnt FROM member_frog f "
        "JOIN member_exp e USING (uid)"
    ).fetchall()
    conn.close()
    return {
        r[0]: {"n": r[1], "f": r[2], "c": r[3], "msg": r[4]} for r in rows
    }


async def main() -> None:
    print(f"booting v2 stack against {DB}")
    before = snapshot()
    total_normal_before = sum(s["n"] for s in before.values())
    total_frozen_before = sum(s["f"] for s in before.values())
    print(
        f"  before: members={len(before)} normal={total_normal_before} "
        f"frozen={total_frozen_before}"
    )

    bot = CazzuBot(
        Config(
            token="fake-token",
            owner_id=int(os.getenv("OWNER_ID", "1")),
            guild_id=int(os.getenv("GUILD_ID", "293796316193095690")),
            db_path=str(DB),
            debug=True,
        )
    )

    async def _ready() -> None:
        pass

    bot.wait_until_ready = _ready  # type: ignore[method-assign]

    await bot.setup_hook()

    try:
        after = snapshot()
        total_normal_after = sum(s["n"] for s in after.values())
        total_frozen_after = sum(s["f"] for s in after.values())

        settings_store = Settings(bot.db)
        now = pendulum.now("UTC")
        this_quarter = (now.year, (now.month - 1) // 3)
        last_q_raw = await settings_store.get("quarterly.last_quarterly")
        freeze_expected = True
        if last_q_raw:
            last_q = pendulum.parse(last_q_raw)
            freeze_expected = this_quarter > (
                last_q.year,
                (last_q.month - 1) // 3,
            )

        if freeze_expected:
            # first boot after a stale quarterly marker: catch-up freeze
            check(
                total_normal_after == 0
                and total_frozen_after
                == total_frozen_before + total_normal_before,
                "quarterly catch-up freeze ran (normal -> frozen)",
                f"normal {total_normal_before} -> {total_normal_after}, "
                f"frozen {total_frozen_before} -> {total_frozen_after}",
            )
        else:
            # live/steady state: this boot must not change balances
            check(
                total_normal_after == total_normal_before
                and total_frozen_after == total_frozen_before,
                "quarterly state steady (no freeze due)",
                f"normal={total_normal_after} frozen={total_frozen_after}",
            )

        # daily reset must NOT have forced (last_daily is today)
        msg_drift = [
            uid
            for uid, s in before.items()
            if after[uid]["msg"] != s["msg"]
        ]
        check(
            not msg_drift,
            "daily reset did not force",
            f"{len(msg_drift)} msg_cnt changed",
        )

        conn = sqlite3.connect(DB)
        frog_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE tag = 'frog'"
        ).fetchone()[0]
        spawn_rows = conn.execute(
            "SELECT COUNT(*) FROM frog_spawn"
        ).fetchone()[0]
        conn.close()
        enabled = bool(await settings_store.get("frog.enabled"))
        expected = spawn_rows if enabled else 0
        check(
            frog_tasks == expected,
            "frog spawn tasks match config",
            f"enabled={enabled} spawns={spawn_rows} tasks={frog_tasks}",
        )

        # read paths
        top = (await exp_db.lifetime_ranked(bot.db))[:3]
        print("  lifetime top3:", top)
        check(len(top) == 3, "lifetime_ranked returns rows")

        season = (now.year, (now.month - 1) // 3)
        seas = await exp_db.seasonal_ranked(bot.db, *season)
        print(f"  seasonal {season} participants: {len(seas)}")
        check(
            len(seas) > 0, "seasonal_ranked (current season) returns rows"
        )

        thr = await ranks_db.get(bot.db, mode=WindowEnum.SEASONAL)
        check(len(thr) == 11, "seasonal rank thresholds", f"{len(thr)}")
        lvl = await exp_db.seasonal_exp(bot.db, top[0][1], *season)
        check(
            levels.level_from_exp(lvl) >= 0,
            "exp -> level math on migrated data",
        )

        settings = settings_store
        all_s = await settings.all()
        expected_keys = (
            "inktober.cid",
            "level.message",
            "level.quiet",
            "rank.seasonal.message",
            "rank.seasonal.enabled",
            "rank.seasonal.keep_old",
            "rank.lifetime.message",
            "rank.lifetime.enabled",
            "rank.lifetime.keep_old",
            "frog.message",
            "frog.enabled",
            "welcome.enabled",
            "welcome.default_rid",
            "welcome.cid",
            "welcome.message",
            "welcome.mode",
            "welcome.monitor_rid",
            "daily.last_daily",
            "quarterly.last_quarterly",
        )
        missing = [k for k in expected_keys if k not in all_s]
        check(
            not missing,
            "migrated settings present",
            f"{len(all_s)} keys, missing={missing or 'none'}",
        )
    finally:
        await bot.close()

    print()
    if FAILS:
        print(f"BOOT CHECK FAILED ({len(FAILS)}):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("BOOT CHECK OK — database is steady-state and ready")


if __name__ == "__main__":
    asyncio.run(main())
