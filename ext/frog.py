"""Allows the hotswapping of extensions/cogs."""

import logging
import os
import random
from typing import TYPE_CHECKING

import discord
import pendulum
from discord.ext import commands, tasks
from pendulum import DateTime

from main import CazzuBot
from src.db import frog, table, task
from src.ntlp import InvalidTimeError, normalize_time_str, parse_duration


if TYPE_CHECKING:
    from asyncpg import Record


_log = logging.getLogger(__name__)


class Frog(commands.Cog):
    def __init__(self, bot: CazzuBot):
        self.bot: CazzuBot = bot
        self.check_spawn_frog.start()

    def cog_unload(self):
        self.check_spawn_frog.cancel()

    def cog_check(self, ctx):
        return ctx.author.id == self.bot.owner_id

    @tasks.loop(seconds=1)
    async def check_spawn_frog(self):
        """Check at regular invervals if we need to spawn a frog.

        We know we need to spawn a frog if the time now is past the the "run_at" under
        the task query with tags "frog".
        """
        # _log.info("Checking if frog can spawn...")

        now = pendulum.now("UTC")
        records: list[Record] = await task.get(self.bot.pool, tag=["frog"])
        # _log.info(f"{records=}")

        if not records:
            return  # no frogs to handle

        expired: list[Record] = [item for item in records if item["run_at"] < now]

        frogs: list[table.Task] = [table.Task(**ex) for ex in expired]
        # for frog in frogs:  # Decode payload string to json dictionary object
        # frog.payload = self.bot.json_decoder.decode(frog.payload)
        # _log.info(frog.payload)

        # _log.info(frogs)

        for frog in frogs:
            _log.info("Spawning frog...")
            gid = frog.payload["gid"]
            cid = frog.payload["cid"]
            interval = frog.payload["interval"]
            fuzzy = frog.payload["fuzzy"]
            id = frog.id
            # _log.info(f"Frog will spawn in {gid}:{cid}")

            guild = self.bot.get_guild(gid)
            # _log.info(guild)
            channel = guild.get_channel(cid)
            # _log.info(channel)
            await channel.send("🥔")

            # Only roll and update run_at
            run_at = self.roll_future_frog(now, interval, fuzzy)
            await task.frog_update_run(self.bot.pool, id, run_at)

    @check_spawn_frog.before_loop
    async def before_check_frog_spawn(self):
        await self.bot.wait_until_ready()

    @commands.group()
    async def frog(self, ctx):
        pass

    @frog.command(name="register")
    async def frog_register(
        self,
        ctx: commands.Context,
        interval: str,
        persist: int = 30,
        fuzzy: float = 0.3,
        channel: discord.TextChannel = None,
    ):
        """Register this channel as a channel that can spawn frogs.

        If the channel already exists, it will overwrite the settings.

        Interval uses natural duration processing, at least 1 frog every interval.
        Persist is in seconds, how many seconds a frog stays until disappearing.
        Fuzzy is a decimal percent, the randomness of spawning intervals.
        """
        now = pendulum.now()

        if channel is None:
            channel = ctx.channel

        # if fuzzy < 0 or fuzzy > 1:
        #     msg = "Fuzzy must be between 0 and 1."
        #     raise commands.BadArgument(msg)

        # if persist < 3 or persist > 120:
        #     msg = "Persist must be between 3 and 120 seconds."
        #     raise commands.BadArgument(msg)

        cid = channel.id
        gid = ctx.guild.id

        try:
            interval = parse_duration(interval).in_seconds()
        except InvalidTimeError as err:
            msg = f"Interval {interval} is not a valid time."
            raise commands.BadArgument(msg) from err

        # if interval < 60:
        #     msg = "Inverval must be greater than 60 seconds."
        #     raise commands.BadArgument(msg)
        # End argument checking

        # Update per-guild frog settngs.
        fg = table.Frog(gid, cid, interval, persist, fuzzy)
        await frog.upsert(self.bot.pool, fg)

        # Now we need to update any ongoing tasks, and if not, create it.
        # Not only do we need to reroll run_at, but we need to update payload.
        payload = self.generate_payload(gid, cid, interval, persist, fuzzy)
        record = await task.get_one(
            self.bot.pool,
            payload={"gid": gid, "cid": cid},
            tag=["frog"],
        )

        if record is not None:  # If a task already exists
            id = record["id"]
            run_at = self.roll_future_frog(now, interval, fuzzy)

            # payload = self.bot.json_encoder.encode(payload)
            await task.frog_update(self.bot.pool, id, run_at, payload)
        else:  # If task not already exists
            await self.add_frog_task(payload)

        await ctx.message.add_reaction("👍")

    @frog.command(name="clear")
    async def frog_clear(self, ctx: commands.Context):
        """Remove all frog settings for this guild,.

        Also stops frog tasks for this guild.
        """
        gid = ctx.guild.id
        await frog.clear(self.bot.pool, gid)
        await task.drop(self.bot.pool, tag=["frog"], payload={"gid": gid})
        await ctx.message.add_reaction("👍")

    async def add_frog_task(self, payload: dict):
        """Add the task for frog future spawn.

        Frogs spawn within some interval, slightly offset either positively or
        negatively by some % designated by fuzzy.

        Interval and persist should be in seconds.
        """
        now = pendulum.now()
        interval = payload["interval"]
        fuzzy = payload["fuzzy"]

        run_at = self.roll_future_frog(now, interval, fuzzy)

        payload = payload
        tsk = table.Task(["frog"], run_at, payload)

        await task.add(self.bot.pool, tsk)

    def generate_payload(
        self, gid: int, cid: int, interval: int, persist: int, fuzzy: float
    ) -> dict | str:
        return {
            "gid": gid,
            "cid": cid,
            "interval": interval,
            "persist": persist,
            "fuzzy": fuzzy,
        }

    async def update_frog_task(
        self, id: int, now: DateTime, interval: int, fuzzy: float
    ):
        run_at = self.roll_future_frog(now, interval, fuzzy)
        await task.frog_update_run(self.bot.pool, id, run_at)

    def roll_fuzzy(self, fuzzy: float):
        return ((random.random() - 0.5) * 2) * fuzzy

    def roll_future_frog(self, now: DateTime, interval: int, fuzzy: float):
        fuzzy_duration = interval * (1 + self.roll_fuzzy(fuzzy))
        return now + pendulum.duration(seconds=fuzzy_duration)


async def setup(bot: commands.Bot):
    await bot.add_cog(Frog(bot))
