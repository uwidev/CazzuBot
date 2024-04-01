"""Experience calculations and management.

See member_exp_log.py for details on how exp is stored and summed.
"""

import logging
from enum import Enum, auto
from math import trunc
from typing import TYPE_CHECKING, NamedTuple

import discord
import pendulum
from asyncpg import Record
from discord.ext import commands

from main import CazzuBot
from src import db, leaderboard, level, levels_helper, rank, utility


_log = logging.getLogger(__name__)

# Global Variables for Experience rates
#
# These variables are never meant to be modified except through hard code.
# These variables, especially the cooldown and exp reset, are not changed upon cog reload at the moment.
# Im just having some some problems when it comes to cancelling a task and restarting it. Maybe in the future when I'm more used
# to tasks it might be feasible, but for now, if you ever need to change these values, it's best to restart the bot.
_BASE = 1
_BONUS = 20
_UNTIL_MSG = 77
_DECAY_FACTOR = 2
_EXP_COOLDOWN = 15  # seconds
_EXP_BUFF_RESET = 1440  # mins    |   1440m = 24h

_SCOREBOARD_STAMP = "https://cdn.discordapp.com/emojis/695126165756837999.webp?size=160&quality=lossless"


def _from_msg(msg: int):
    """Return the expected experience reward given the total message count."""
    if msg < 0:
        msg = "Negative messages should not exist when calculating experience"
        _log.error(msg)
        raise ValueError(msg)

    if msg >= _UNTIL_MSG:
        return _BASE

    return round(
        (_BASE * _BONUS)
        - (_BASE * _BONUS - _BASE) * (msg / _UNTIL_MSG) ** _DECAY_FACTOR,
    )


# dict of message count to its rewarded exp, starting at 1
RE_MSG_EXP_CUMULATIVE = dict()
RE_MSG_EXP_CUMULATIVE[1] = _BASE + _from_msg(0)

for i in range(2, _UNTIL_MSG + 1):
    RE_MSG_EXP_CUMULATIVE[i] = RE_MSG_EXP_CUMULATIVE[i - 1] + _BASE + _from_msg(i - 1)


class Experience(commands.Cog):
    def __init__(self, bot: CazzuBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Add experience to the member based on prior activity.

        Also checks for potential level ups. Level ups are CURRENTLY based on lifetime
        exp, and should eventually be switched to seasonal experience.
        """
        if self.bot.debug and message.author.id not in self.bot.debug_users:
            return

        if message.author.bot:  # ignore other bots
            return

        if message.author.id == self.bot.user.id:  # ignore self
            return

        # if message.author.id != 92664421553307648:  # debug, only see usara
        #     return

        _log.debug("Received message from %s", message.author)
        _log.debug("%s", message)

        now = pendulum.now("UTC")
        uid = message.author.id
        gid = message.guild.id

        member_db = await db.member_exp.get_one(self.bot.pool, gid, uid)
        if member_db is None:  # Member not found, insert and try again.
            await db.member_exp.add(
                self.bot.pool,
                db.table.MemberExp(gid, uid, 0, 0, now.subtract(hours=1)),
            )
            member_db = await db.member_exp.get_one(self.bot.pool, gid, uid)

        if member_db and now < member_db.get("cdr"):
            return  # Cooldown has not yet expired, do nothing

        # Prepare and pack variables
        msg_cnt = member_db.get("msg_cnt") + 1
        exp_gain = _from_msg(msg_cnt)

        year = now.year
        month = now.month
        seasonal_exp_old = utility.else_if_none(
            await db.member_exp_log.get_seasonal_by_month(
                self.bot.pool, gid, uid, year, month
            ),
            0,
        )
        seasonal_exp_new = seasonal_exp_old + exp_gain
        seasonal_exp = utility.OldNew(seasonal_exp_old, seasonal_exp_new)

        lifetime_exp_old = member_db.get("lifetime")
        lifetime_exp_new = lifetime_exp_old + exp_gain
        lifetime_exp = utility.OldNew(lifetime_exp_old, lifetime_exp_new)

        seasonal_level_old = levels_helper.level_from_exp(seasonal_exp_old)
        seasonal_level_new = levels_helper.level_from_exp(seasonal_exp_new)
        seasonal_level = utility.OldNew(seasonal_level_old, seasonal_level_new)

        lifetime_level_old = levels_helper.level_from_exp(lifetime_exp_old)
        lifetime_level_new = levels_helper.level_from_exp(lifetime_exp_new)
        lifetime_level = utility.OldNew(lifetime_level_old, lifetime_level_new)

        # Add to member's lifetime exp
        offset_cooldown = now + pendulum.duration(seconds=_EXP_COOLDOWN)
        member_updated = db.table.MemberExp(
            gid, uid, lifetime_exp.new, msg_cnt, offset_cooldown
        )
        await db.member_exp.update_exp(self.bot.pool, member_updated)

        # Add to loggings for seasonal (and weekly, monthly, etc.)
        await db.member_exp_log.add(
            self.bot.pool, db.table.MemberExpLog(gid, uid, exp_gain, now)
        )

        # Deal with potential level up
        await level.on_msg_handle_levels(self.bot, message, seasonal_level)

        # Deal with potential rank up
        # We do not check for level up because we still want to have rank integrity
        await rank.on_msg_handle_ranks(
            self.bot, message, seasonal_level, lifetime_level
        )

    @commands.group(aliases=["xp", "experience"], invoke_without_command=True)
    async def exp(self, ctx: commands.Context, *, user: discord.Member = None):
        """Show season's experience and leaderboards."""
        if user is None:
            user = ctx.message.author

        now = pendulum.now()
        gid = ctx.guild.id

        rows = await db.guild.get_members_exp_seasonal_by_month(
            self.bot.pool, gid, now.year, now.month
        )  # month needs to be zero indexed to properly bin into seasons

        embed = await self._prepare_personal_summary(ctx, user, rows)

        await ctx.send(embed=embed)

    @exp.command(name="lifetime")
    async def exp_lifetime(self, ctx: commands.Context, *, user: discord.Member = None):
        """Lifetime experience variant."""
        if user is None:
            user = ctx.message.author

        gid = ctx.guild.id
        rows = await db.guild.get_members_exp_ranked(self.bot.pool, gid)
        embed = await self._prepare_personal_summary(
            ctx, user, rows, db.table.WindowEnum.LIFETIME
        )

        await ctx.send(embed=embed)

    async def _prepare_personal_summary(
        self,
        ctx: commands.Context,
        user: discord.Member,
        data: list[Record],
        mode: db.table.WindowEnum = db.table.WindowEnum.SEASONAL,
    ) -> discord.Embed:
        """Return the embed of scoreboard Club Membership Card.

        data: the raw result from query, containing (rank, uid, exp) in that order
        """
        uid = user.id

        # Prepare leaderboard window
        uid_index = [r["uid"] for r in data].index(uid)
        subset, subset_i = leaderboard.create_data_subset(data, uid_index)

        # Transpose for per-column transformations
        ranks, uids, exps = zip(*subset)
        lvls = [levels_helper.level_from_exp(e) for e in exps]

        # Annoying bug to learn from, and python programming misunderstanding.
        #
        # List Comprehension (speculative, but sound) seems to execute expressions
        # immediately to build the list; there is no generator formed and casted to
        # list.
        #
        # Generator Comprehension, when there's an await, will return an async
        # generator. When immediately passed into list() to cast it, it won't work
        # because its implementaion is only for synchronous iterators, not async.
        # In other words, do not list(await x for x in arr), instead, do list comp.
        #
        # Even if the expression may stall, since they are await'ed, it shouldn't stall
        # the loop. So for generator purposes, there's no purpose to use asyncstdlib.
        names = [await utility.find_username(self.bot, ctx, id) for id in uids]

        # Transpose back to prepare to generate
        window = list(zip(ranks, exps, lvls, names))

        # Generate leaderboard
        headers = ["Rank", "Exp", "Lv", "User"]
        align = ["<", ">", ">", ">"]
        max_padding = [0, 0, 0, 16]

        raw_scoreboard = leaderboard.format(
            window,
            headers,
            align=align,
            max_padding=max_padding,
        )

        col_widths = leaderboard.calc_max_col_width(window, headers, max_padding)

        _log.debug(f"{raw_scoreboard=}")
        leaderboard.highlight_row(raw_scoreboard, subset_i, col_widths)
        scoreboard_s = "\n".join(raw_scoreboard)  # Final step to join.

        # Other Preparation
        gid = ctx.guild.id
        rid = await db.rank_threshold.of_member(self.bot.pool, gid, uid, mode=mode)
        role: discord.Role = ctx.guild.get_role(rid)

        # Generate Embed
        embed = discord.Embed()
        lvl = lvls[subset_i]
        exp = exps[subset_i]
        rank = ranks[subset_i]

        if mode is db.table.WindowEnum.SEASONAL:
            now = pendulum.now()
            year = now.year
            month = now.month

            total_member_count = (
                await db.member_exp_log.get_seasonal_total_members_by_month(
                    self.bot.pool, gid, year, month
                )
            )
        elif mode is db.table.WindowEnum.LIFETIME:
            total_member_count = await db.member_exp_log.get_total_members(
                self.bot.pool, gid
            )

        percentile = utility.calc_percentile(rank, total_member_count)

        embed.set_author(
            name=f"{user.display_name}'s Club Membership Card",
            icon_url=_SCOREBOARD_STAMP,
        )
        embed.set_thumbnail(url=user.avatar.url)
        embed.description = f"""
        Rank: {role.mention if role else '`None`'}
        Level: **`{lvl:,}`**
        Experience: **`{exp:,}`**

        You currently the `{utility.ordinal(trunc(percentile))}` percentile of all members!
        ```py\n{scoreboard_s}```"""

        embed.color = discord.Color.from_str("#a2dcf7")

        return embed

    @exp.command(name="resync")
    @commands.is_owner()
    @utility.author_confirm()
    async def exp_resync(self, ctx: commands.Context):
        _log.info(f"{ctx.author} called for resync of member lifetime exp")

        msg = await ctx.send("Starting frog sync...")
        await db.member_exp.sync_with_exp_logs(self.bot.pool)
        await msg.edit(content="Synced! ✅")


async def setup(bot: commands.Bot):
    await bot.add_cog(Experience(bot))
