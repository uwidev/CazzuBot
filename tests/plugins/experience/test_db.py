"""Experience repository (db) layer — ported from scripts/functest.py."""

from __future__ import annotations

import pendulum

from core.bot import CazzuBot
from core.models import MemberExpLogSourceEnum
from plugins.experience import db as exp_db

_UID = 424242


async def test_exp_log_and_seasonal_ranked(bot: CazzuBot) -> None:
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, _UID)
    await exp_db.add_exp_log(bot.db, _UID, 50, now)
    await exp_db.add_exp_log(bot.db, _UID, 30, now.add(seconds=1))
    await exp_db.add_exp_log(bot.db, 777, 100, now)

    member = await exp_db.get_member_exp(bot.db, _UID)
    assert member is not None and member.lifetime == 0  # not synced yet

    seasonal = await exp_db.seasonal_exp(
        bot.db, _UID, now.year, (now.month - 1) // 3
    )
    assert seasonal == 80
    ranked = await exp_db.seasonal_ranked(
        bot.db, now.year, (now.month - 1) // 3
    )
    assert ranked[0] == (1, 777, 100) and ranked[1][0] == 2


async def test_sync_with_exp_logs(bot: CazzuBot) -> None:
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, _UID)
    await exp_db.add_exp_log(bot.db, _UID, 50, now)
    await exp_db.sync_with_exp_logs(bot.db)
    member = await exp_db.get_member_exp(bot.db, _UID)
    assert member is not None and member.lifetime == 50


async def test_chat_readers_ignore_frog_rows(bot: CazzuBot) -> None:
    """The ladder is chatting-only: FROG rows stay but feed no reader.

    Exp reverted to a pure measure of chatting (2026-09), so every chat
    reader filters to ``source = 'message'`` and a frog-only member earns
    no exp, ranks nowhere, and never reaches the seasonal denominator.
    """
    now = pendulum.now("UTC")
    season = (now.month - 1) // 3
    frog_only, chat_uid = 888, 666
    await exp_db.add_member_exp(bot.db, _UID)
    await exp_db.add_member_exp(bot.db, frog_only)
    await exp_db.add_member_exp(bot.db, chat_uid)
    await exp_db.add_exp_log(bot.db, _UID, 50, now)
    await exp_db.add_exp_log(
        bot.db, _UID, 5000, now, source=MemberExpLogSourceEnum.FROG
    )
    await exp_db.add_exp_log(
        bot.db, frog_only, 900, now, source=MemberExpLogSourceEnum.FROG
    )
    await exp_db.add_exp_log(bot.db, chat_uid, 30, now)
    # a log-only uid — message rows but no member_exp row (1,299 of them in
    # the live DB), dated out of this season so the seasonal readers below
    # keep their own expectations
    await exp_db.add_exp_log(bot.db, 999, 10, now.subtract(years=1))

    # the same member's chat exp ignores their own frog rows
    assert await exp_db.seasonal_exp(bot.db, _UID, now.year, season) == 50
    # a frog-only member has no chat exp at all
    assert (
        await exp_db.seasonal_exp(bot.db, frog_only, now.year, season) == 0
    )
    ranked = await exp_db.seasonal_ranked(bot.db, now.year, season)
    assert [uid for _rank, uid, _exp in ranked] == [_UID, chat_uid]
    # the seasonal denominator counts this season's chat earners only
    assert (
        await exp_db.seasonal_total_members(bot.db, now.year, season) == 2
    )

    await exp_db.sync_with_exp_logs(bot.db)
    # lifetime rebuilds from MESSAGE rows only: the frog exp is dropped
    uid_row = await exp_db.get_member_exp(bot.db, _UID)
    frog_row = await exp_db.get_member_exp(bot.db, frog_only)
    assert uid_row is not None and uid_row.lifetime == 50
    assert frog_row is not None and frog_row.lifetime == 0
    # the frog rows themselves are untouched history
    assert (
        await bot.db.fetchval(
            "SELECT COUNT(*) FROM member_exp_log WHERE source = 'frog'"
        )
        == 2
    )


async def test_lifetime_denominator_is_the_board_population(
    bot: CazzuBot,
) -> None:
    """``total_members`` counts ``member_exp`` rows — what the board boards.

    The lifetime card divides the member's rank by this to print their
    percentile, so it has to be the lifetime board's own population: a
    log-only uid (message rows but no row — 1,299 of them in the live DB)
    must not inflate it. Counting the log meant a COUNT(DISTINCT) over
    every exp row, which overran Discord's 3s response window on the live
    DB and left the card unanswered ("The application did not respond").
    """
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, _UID)
    await exp_db.add_exp_log(bot.db, _UID, 50, now)
    await exp_db.sync_with_exp_logs(bot.db)
    await exp_db.add_member_exp(bot.db, 888)  # a row, but no exp yet
    await exp_db.add_exp_log(bot.db, 999, 10, now)  # log-only: no row

    rows = await exp_db.lifetime_ranked(bot.db)
    assert [uid for _rank, uid, _exp in rows] == [_UID, 888]
    assert await exp_db.total_members(bot.db) == len(rows)


async def test_update_member_exp(bot: CazzuBot) -> None:
    await exp_db.add_member_exp(bot.db, _UID)
    await exp_db.update_member_exp(
        bot.db,
        _UID,
        lifetime=80,
        msg_cnt=5,
        cdr=pendulum.now("UTC").add(seconds=15),
    )
    member = await exp_db.get_member_exp(bot.db, _UID)
    assert member is not None and member.msg_cnt == 5
