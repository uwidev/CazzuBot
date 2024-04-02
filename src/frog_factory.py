"""Manages spawning of frogs, namely through their tasks."""

import json
import logging
import os
import random
from asyncio import TimeoutError
from enum import Enum
from math import trunc
from typing import TYPE_CHECKING

import discord
import pendulum
from discord.ext import commands, tasks
from pendulum import DateTime

from main import CazzuBot
from src import db, frog, leaderboard, user_json, utility
from src.custom_converters import PositiveInt
from src.ntlp import InvalidTimeError, parse_duration


_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from asyncpg import Record


async def check_frog_spawn(bot: CazzuBot):
    now = pendulum.now("UTC")
    records: list[Record] = await db.task.get(bot.pool, tag=["frog"])

    if not records:
        return  # no frogs to handle

    expired_frog_record: list[Record] = [
        item for item in records if item["run_at"] < now
    ]

    expired_frog_task: list[db.table.Task] = [
        db.table.Task(**ex) for ex in expired_frog_record
    ]

    for expired in expired_frog_task:  # would be better to batch so only 1 db call
        await db.task.drop_one(bot.pool, expired.id)

    for fg in expired_frog_task:
        gid = fg.payload["gid"]

        # When a guild disables frog, frog tasks should be cleared as well.
        # Checking if enabled is redundant, since it shouldn't be possible for a
        # task to exist after a guild disables them.
        # enabled = await db.frog.get_enabled(bot.pool, gid)
        # if not enabled:
        #     return

        cid = fg.payload["cid"]
        interval = fg.payload["interval"]
        persist = fg.payload["persist"]
        fuzzy = fg.payload["fuzzy"]
        id = fg.id

        was_captured = await spawn_and_wait(bot, persist, gid=gid, cid=cid)

        # Roll next spawn and update run_at
        # From earlier comment, it when a frog despawns/is captured, it
        # automatically gets added as a new task. It should ensure that it doesn't
        # conflict with the guild's frog enabled setting, as if disabled, frogs
        # shouldn't be spawning at all anymore.
        enabled = await db.frog.get_enabled(bot.pool, gid)
        if not enabled:
            return

        now = pendulum.now()
        run_at = roll_future_frog(now, interval, fuzzy)
        fg.run_at = run_at
        await db.task.add(bot.pool, fg)


async def spawn_and_wait(
    bot: CazzuBot,
    persist: int,
    *,
    ctx: commands.Context = None,
    gid: int = None,
    cid: int = None,
):
    """Spawn frog and wait until capture.

    Return True if captured, else False.

    Requires EXCLUSIVELY context OR gid and cid to spawn properly.
    """
    if ctx is not None:
        guild = ctx.guild
        gid = guild.id
        channel = ctx.channel
    else:
        guild = bot.get_guild(gid)
        channel = bot.get_channel(cid)

    _log.debug(f"Spawning frog in {guild.name}, {channel.name}...")
    msg = await channel.send("<:cirnoFrog:695126166301835304>")
    await msg.add_reaction("<:cirnoNet:752290769712316506>")

    def check(reaction: discord.Reaction, user: discord.User):
        return (
            reaction.message.id == msg.id
            and str(reaction.emoji) == "<:cirnoNet:752290769712316506>"
            and not user.bot
        ) or (bot.debug and user.id == bot.owner_id)

    reaction: discord.Reaction
    catcher: discord.User
    try:
        reaction, catcher = await bot.wait_for(
            "reaction_add", timeout=persist, check=check
        )  # wait for catch, if caught continue
        now = pendulum.now()
        uid = catcher.id

        frog_type = db.table.FrogTypeEnum.NORMAL  # for now until fancy frogs

        log = db.table.MemberFrogLog(gid, uid, frog_type, now)
        await db.member_frog_log.add(bot.pool, log)

        await db.member_frog.modify_frog(
            bot.pool,
            gid,
            uid,
            modify=1,
            frog_type=frog_type,
        )

        # change lifetime cap
        await db.member_frog.modify_capture(bot.pool, gid, uid, modify=1)

        embed_json = await db.frog.get_message(bot.pool, gid)
        frog_cnt_total = await db.member_frog.get_frogs(bot.pool, gid, uid)
        frog_cnt_seasonal = await db.member_frog_log.get_seasonal_by_month(
            bot.pool, gid, uid, now.year, now.month
        )

        utility.deep_map(
            embed_json,
            frog.formatter,
            member=catcher,
            frog_cnt_old=frog_cnt_total - 1,
            frog_cnt_new=frog_cnt_total,
            seasonal_cap_old=frog_cnt_seasonal - 1,
            seasonal_cap_new=frog_cnt_seasonal,
        )

        content, embed, embeds = user_json.prepare(embed_json)

        await channel.send(content, embed=embed, embeds=embeds, delete_after=7)
    except TimeoutError:
        return False
    else:
        return True
    finally:
        await msg.delete()


async def clear_guild_frog_task(bot: CazzuBot, gid: int):
    """Clear a guild's frog tasks."""
    await db.task.drop(bot.pool, payload={"gid": gid}, tag=["frog"])


async def clear_frog_task(bot: CazzuBot):
    """Clear all frog tasks."""
    await db.task.drop(bot.pool, tag=["frog"])


async def queue_frog_spawns(bot: CazzuBot, frog_spawns: list[db.table.FrogSpawn]):
    """Spawn frogs given a list of FrogSpawn objects.

    Frogs will not spawn if a guild has disabled them.
    """
    now = pendulum.now()
    run_ats = [roll_future_frog(now, frog.interval, frog.fuzzy) for frog in frog_spawns]

    task_rows: list[db.table.Task] = [
        db.table.Task(["frog"], run_ats[i], frog_spawns[i].__dict__)
        for i in range(len(frog_spawns))
    ]

    enabled_records = await db.frog.get_enabled_guilds(bot.pool)
    enabled_gids = [record.get("gid") for record in enabled_records]

    filtered_tasks = list(
        filter(lambda task: task.payload["gid"] in enabled_gids, task_rows)
    )

    await db.task.add_many(bot.pool, filtered_tasks)


async def reset_frog_tasks(bot: CazzuBot):
    """Clear all frog tasks and re-inserts new tasks per all guild settings."""
    _log.info("Cleaning and preparing up frog spawn tasks...")
    await clear_frog_task(bot)

    records = await db.frog_spawn.get_all(bot.pool)
    frog_spawns: list[db.table.FrogSpawn] = [
        db.table.FrogSpawn(*record) for record in records
    ]

    await queue_frog_spawns(bot, frog_spawns)


async def reset_guild_frog_tasks(bot: CazzuBot, gid: int):
    """Clear a guild's frog tasks and re-inserts new tasks per guild settings."""
    await clear_guild_frog_task(bot, gid)

    records = await db.frog_spawn.get(bot.pool, gid)
    frog_spawns: list[db.table.FrogSpawn] = [
        db.table.FrogSpawn(*record) for record in records
    ]

    await queue_frog_spawns(bot, frog_spawns)


async def update_frog_task(
    bot: CazzuBot, id: int, now: DateTime, interval: int, fuzzy: float
):
    run_at = roll_future_frog(now, interval, fuzzy)
    await db.task.frog_update_run(bot.pool, id, run_at)


def roll_fuzzy(fuzzy: float):
    return ((random.random() - 0.5) * 2) * fuzzy


def roll_future_frog(now: DateTime, interval: int, fuzzy: float):
    fuzzy_persist = interval * (1 + roll_fuzzy(fuzzy))
    return now + pendulum.duration(seconds=fuzzy_persist)


async def add_frog_task(bot: CazzuBot, payload: dict):
    """Add the task for frog future spawn.

    Frogs spawn within some interval, slightly offset either positively or
    negatively by some % designated by fuzzy.

    Interval and persist should be in seconds.
    """
    now = pendulum.now()
    interval = payload["interval"]
    fuzzy = payload["fuzzy"]
    run_at = roll_future_frog(now, interval, fuzzy)

    tsk = db.table.Task(["frog"], run_at, payload)

    await db.task.add(bot.pool, tsk)
