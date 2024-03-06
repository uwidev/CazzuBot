"""Allows the hotswapping of extensions/cogs."""

import json
import logging
import os
import random
from asyncio import TimeoutError
from typing import TYPE_CHECKING

import discord
import pendulum
from discord.ext import commands, tasks
from pendulum import DateTime

from main import CazzuBot
from src import db, frog, user_json, utility
from src.custom_converters import PositiveInt
from src.ntlp import InvalidTimeError, parse_duration


if TYPE_CHECKING:
    from asyncpg import Record


_log = logging.getLogger(__name__)


class Frog(commands.Cog):
    def __init__(self, bot: CazzuBot):
        self.bot: CazzuBot = bot
        self.check_spawn_frog.start()

    async def cog_load(self):
        await self._reset_frog_tasks()

    async def cog_unload(self):
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
        records: list[Record] = await db.task.get(self.bot.pool, tag=["frog"])
        # _log.info(f"{records=}")

        if not records:
            return  # no frogs to handle

        expired: list[Record] = [item for item in records if item["run_at"] < now]

        frogs: list[db.table.Task] = [db.table.Task(**ex) for ex in expired]
        # for frog in frogs:  # Decode payload string to json dictionary object
        # frog.payload = self.bot.json_decoder.decode(frog.payload)
        # _log.info(frog.payload)

        # _log.info(frogs)

        for record in frogs:  # would be better to batch so only 1 db call
            await db.task.drop_one(self.bot.pool, record.id)

        for fg in frogs:
            gid = fg.payload["gid"]
            cid = fg.payload["cid"]
            interval = fg.payload["interval"]
            persist = fg.payload["persist"]
            fuzzy = fg.payload["fuzzy"]
            id = fg.id

            guild = self.bot.get_guild(gid)
            channel = guild.get_channel(cid)

            _log.debug(f"Spawning frog in {guild.name=}, {channel.name=}...")
            msg = await channel.send("🥔")
            await msg.add_reaction("🍆")

            def check(reaction: discord.Reaction, user: discord.User):
                return (
                    reaction.message.id == msg.id
                    and str(reaction.emoji) == "🍆"
                    and not user.bot
                ) or (self.bot.debug and user.id == self.bot.owner_id)

            reaction: discord.Reaction
            catcher: discord.User
            try:
                reaction, catcher = await self.bot.wait_for(
                    "reaction_add", timeout=persist, check=check
                )  # wait for catch, if caught continue
                uid = catcher.id
                await db.member_frog.upsert_modify_frog(
                    self.bot.pool, db.table.MemberFrog(gid, uid, 1), 1
                )
                embed_json = await db.frog.get_message(self.bot.pool, gid)
                member_frog = await db.member_frog.get_amount(self.bot.pool, gid, uid)
                _log.info(f"{embed_json=}")
                utility.deep_map(
                    embed_json,
                    frog.formatter,
                    member=catcher,
                    frog_old=member_frog - 1,
                    frog_new=member_frog,
                )

                content, embed, embeds = user_json.prepare(embed_json)

                _log.info(f"{embed_json=}")

                await channel.send(content, embed=embed, embeds=embeds)
            except TimeoutError:
                pass
            finally:
                await msg.delete()

            # Roll next spawna and update run_at
            now = pendulum.now()
            run_at = self.roll_future_frog(now, interval, fuzzy)
            fg.run_at = run_at
            await db.task.add(self.bot.pool, fg)

    @check_spawn_frog.before_loop
    async def before_check_frog_spawn(self):
        await self.bot.wait_until_ready()

    async def _reset_frog_tasks(self):
        """Clear all frog tasks and re-inserts new tasks per all guild settings."""
        _log.info("Cleaning and preparing up frog spawn tasks...")
        await db.task.drop(self.bot.pool, tag=["frog"])
        records = await db.frog_spawn.get_all(self.bot.pool)
        frog_registers: list[db.table.FrogSpawn] = [
            db.table.FrogSpawn(*record) for record in records
        ]

        now = pendulum.now()
        run_ats = [
            self.roll_future_frog(now, frog.interval, frog.fuzzy)
            for frog in frog_registers
        ]

        task_rows = [
            db.table.Task(["frog"], run_ats[i], frog_registers[i].__dict__)
            for i in range(len(frog_registers))
        ]

        await db.task.add_many(self.bot.pool, task_rows)

    @commands.group(invoke_without_command=True)
    async def frog(self, ctx, *, member: discord.Member = None):
        """Show this user's current frog profile."""
        if member is None:
            member = ctx.message.author

        gid = ctx.guild.gid
        uid = member.id
        member_frog = await db.member_frog.get_amount(self.bot.pool, gid, uid)

    async def _prepare_personal_summary(ctx, user, rows):
        pass

    @frog.command(name="register")
    async def frog_register(
        self,
        ctx: commands.Context,
        interval: str,
        persist: str = "30",
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

        cid = channel.id
        gid = ctx.guild.id

        try:
            interval = parse_duration(interval).in_seconds()
        except InvalidTimeError as err:
            msg = f"Interval {interval} is not a valid time."
            raise commands.BadArgument(msg) from err

        if not self.bot.debug or interval < 60:
            msg = "Inverval must be greater than 60 seconds."
            raise commands.BadArgument(msg)
        # End argument checking

        try:
            persist = parse_duration(persist).in_seconds()
        except InvalidTimeError as err:
            msg = f"Persist {persist} is not a valid time."
            raise commands.BadArgument(msg) from err

        if self.bot.debug or persist < 3 or persist > 120:
            msg = "Persist must be between 3 and 120 seconds."
            raise commands.BadArgument(msg)

        if self.bot.debug or fuzzy < 0 or fuzzy > 1:
            msg = "Fuzzy must be between 0 and 1."
            raise commands.BadArgument(msg)

        # Update per-guild frog settngs.
        fg = db.table.FrogSpawn(gid, cid, interval, persist, fuzzy)
        await db.frog_spawn.upsert(self.bot.pool, fg)

        # Now we need to update any ongoing tasks, and if not, create it.
        # Not only do we need to reroll run_at, but we need to update payload.
        payload = self.generate_payload(gid, cid, interval, persist, fuzzy)
        record = await db.task.get_one(
            self.bot.pool,
            payload={"gid": gid, "cid": cid},
            tag=["frog"],
        )

        if record is not None:  # If a task already exists
            id = record["id"]
            run_at = self.roll_future_frog(now, interval, fuzzy)

            # payload = self.bot.json_encoder.encode(payload)
            await db.task.frog_update(self.bot.pool, id, run_at, payload)
        else:  # If task not already exists
            await self.add_frog_task(payload)

        await ctx.message.add_reaction("👍")

    @frog.command(name="clear")
    async def frog_clear(self, ctx: commands.Context):
        """Remove all frog settings for this guild,.

        Also stops frog tasks for this guild.
        """
        gid = ctx.guild.id
        await db.frog_spawn.clear(self.bot.pool, gid)
        await db.task.drop(self.bot.pool, tag=["frog"], payload={"gid": gid})
        await ctx.message.add_reaction("👍")

    @frog.command(name="consume")
    async def frog_consume(self, ctx: commands.Context, amount: PositiveInt = 1):
        if amount < 1:
            msg = "Amount of frogs consume must be greater than 0."
            raise commands.BadArgument(msg)

        gid = ctx.guild.id
        uid = ctx.author.id

        member_frogs = await db.member_frog.get_amount(self.bot.pool, gid, uid)
        if member_frogs is not None and member_frogs - amount < 0:
            msg = f"Member does not have enough frogs ({member_frogs}) to consume."
            raise commands.BadArgument(msg)

        now = pendulum.now()
        exp_amount = 10

        exp_payload = db.table.MemberExpLog(
            gid, uid, exp_amount, now, db.table.MemberExpLogSource.FROG
        )
        await db.member_exp_log.add(self.bot.pool, exp_payload)

        await db.member_frog.upsert_modify_frog(
            self.bot.pool, db.table.MemberFrog(gid, uid), -amount
        )

    @frog.group(name="set")
    @commands.has_permissions(administrator=True)
    async def frog_set(self, ctx):
        pass

    @frog_set.command(name="message", aliases=["msg"])
    async def frog_set_message(self, ctx: commands.Context, *, message: str):
        decoded = await user_json.verify(self.bot, ctx, message)

        gid = ctx.guild.id
        await db.frog.set_message(self.bot.pool, gid, decoded)

    @frog_set.command(name="enabled", aliases=["on"])
    async def frog_set_enabled(self, ctx: commands.Context, val: bool):
        gid = ctx.guild.id
        await db.frog.set_enabled(self.bot.pool, gid, val)

    @frog.command(name="demo")
    async def frog_demo(self, ctx: commands.Context):
        gid = ctx.guild.id
        payload = await db.frog.get_message(self.bot.pool, gid)
        decoded = payload

        member = ctx.author
        utility.deep_map(decoded, frog.formatter, member=member)

        content, embed, embeds = user_json.prepare(decoded)
        await ctx.send(content, embed=embed, embeds=embeds)

    @frog.command(name="raw")
    async def frog_raw(self, ctx: commands.Context):
        gid = ctx.guild.id
        payload = await db.frog.get_message(self.bot.pool, gid)
        await ctx.send(f"```{json.dumps(payload)}```")

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
        tsk = db.table.Task(["frog"], run_at, payload)

        await db.task.add(self.bot.pool, tsk)

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
        await db.task.frog_update_run(self.bot.pool, id, run_at)

    def roll_fuzzy(self, fuzzy: float):
        return ((random.random() - 0.5) * 2) * fuzzy

    def roll_future_frog(self, now: DateTime, interval: int, fuzzy: float):
        fuzzy_persist = interval * (1 + self.roll_fuzzy(fuzzy))
        return now + pendulum.duration(seconds=fuzzy_persist)


async def setup(bot: commands.Bot):
    await bot.add_cog(Frog(bot))
