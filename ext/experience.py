"""Experience calculations and management.

See member_exp_log.py for details on how exp is stored and summed.
"""
import logging
from typing import TYPE_CHECKING

import discord
import pendulum
from asyncpg import Record
from discord.ext import commands
from discord.ext.commands.context import Context

from src import db, levels_helper, utility


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


if TYPE_CHECKING:  # magical?? shit that helps with type checking
    from main import CazzuBot


class Experience(commands.Cog):
    def __init__(self, bot):
        self.bot: CazzuBot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Add experience to the member based on prior activity.

        Also checks for potential level ups. Level ups are CURRENTLY based on lifetime
        exp, and should eventually be switched to seasonal experience.
        """
        if message.author.bot:  # ignore other bots
            return

        if message.author.id == self.bot.user.id:  # ignore self
            return

        # if message.author.id != 92664421553307648:  # debug, only see usara
        #     return

        now = pendulum.now("UTC")
        uid = message.author.id
        gid = message.guild.id

        member_db = await db.member.get(self.bot.pool, gid, uid)
        if not member_db:  # Member not found, insert and try again.
            await db.member.add(
                self.bot.pool,
                db.table.Member(gid, uid, 0, 0, now.subtract(hours=1)),
            )
            member_db = await db.member.get(self.bot.pool, gid, uid)

        if member_db and now < member_db.get("exp_cdr"):
            return  # Cooldown has not yet expired, do nothing

        old_exp = member_db.get("exp_lifetime")  # Needed to determine if level up
        msg_cnt = member_db.get("exp_msg_cnt") + 1
        exp_gain = _from_msg(msg_cnt)
        new_exp = old_exp + exp_gain
        offset_cooldown = now + pendulum.duration(seconds=_EXP_COOLDOWN)

        _log.info("Granting %s exp to %s", exp_gain, message.author)  # for dev purposes

        # Add to member's lifetime exp
        member_updated = db.table.Member(gid, uid, new_exp, msg_cnt, offset_cooldown)
        await db.member.update_exp(self.bot.pool, member_updated)

        # Add to loggings for future calculations (e.g. seasonal, monthly, etc.)
        await db.member_exp_log.add(
            self.bot.pool, db.table.MemberExpLog(gid, uid, exp_gain, now)
        )

        level = await self._on_msg_handle_levels(message, old_exp, new_exp)
        await self._on_msg_handle_ranks(message, level)

    async def _on_msg_handle_levels(
        self, message: discord.Message, old_exp: int, new_exp: int
    ):
        """Handle potential level ups from experience gain."""
        old_level = levels_helper.level_from_exp(old_exp)
        new_level = levels_helper.level_from_exp(new_exp)

        if new_level > old_level:
            _log.info(
                f"{message.author} has leveled up from {old_level} to {new_level}!"
            )

        return new_level

    async def _on_msg_handle_ranks(self, message: discord.Message, level: int):
        """Handle potential rank ups from level ups.

        Also keeps rank integrity regardless of level up.
        """
        ranks = await db.rank.get(self.bot.pool, message.guild.id)
        if not ranks:
            return

        rid, index = utility.calc_min_rank(ranks, level)

        if not rid:  # not even high enough level for any ranks
            return

        member = message.author
        role = message.guild.get_role(rid)
        await member.add_roles(role, reason="Rank up")

        # remove all other roles than applied, convert to role, only remove existing
        ranks.pop(index)
        del_roles = list(map(message.guild.get_role, (r["rid"] for r in ranks)))
        del_roles = filter(lambda r: r in member.roles, del_roles)
        if del_roles:
            await member.remove_roles(*del_roles)

    @commands.group(aliases=["xp"], invoke_without_command=True)
    async def exp(self, ctx: Context, *, user: discord.Member = None):
        """Show season's experience and leaderboards."""
        if user is None:
            user = ctx.message.author

        now = pendulum.now()
        uid = user.id
        gid = ctx.guild.id

        rows = await db.guild.get_members_exp_seasonal(
            self.bot.pool, gid, now.year, now.month // 3
        )

        # Prepare zip to generate scoreboard
        uid_index = [r["uid"] for r in rows].index(uid)
        window_raw, user_window_index = utility.focus_list(rows, uid_index)

        ranks, uids, exps = zip(*window_raw)
        levels = [levels_helper.level_from_exp(e) for e in exps]

        # Annoying bug to learn from.
        #
        # We want members as a list, so we surround the comprehension with [].
        # We do NOT surround it with () and cast it to a list().
        #
        # If we did the latter, we call the synchronous-list casting with an
        # asynchronous generator (beacuse we have await), resulting in 'async generator'
        # object is not iterable because you can't call async in sync.
        members = [
            utility.else_if_none(
                ctx.guild.get_member(id),
                self.bot.get_user(id),
                await self.bot.fetch_user(id),
                id,
            )
            for id in uids
        ]

        names = [member.display_name for member in members]

        # Generate Scoreboard
        window = list(zip(ranks, exps, levels, names))

        raw_scoreboard, paddings = utility.generate_scoreboard(
            window,
            ["Rank", "Exp", "Level", "User"],
            ["<", ">", ">", ">"],
        )

        utility.highlight_scoreboard(raw_scoreboard, user_window_index, paddings[0])
        scoreboard_s = "\n".join(raw_scoreboard)

        # Other Preparation
        gid = ctx.guild.id
        rid = await db.rank.of_member(self.bot.pool, gid, uid)
        role: discord.Role = ctx.guild.get_role(rid)

        # Generate Embed
        embed = discord.Embed()
        lvl = levels[user_window_index]
        exp = exps[user_window_index]
        rank = ranks[user_window_index]

        total_members = ctx.guild.member_count
        percentile = (total_members - rank) / (total_members - 1) * 100.0

        embed.set_author(
            name=f"{ctx.author.display_name}'s Club Membership Card",
            icon_url=_SCOREBOARD_STAMP,
        )
        embed.set_thumbnail(url=ctx.author.avatar.url)
        embed.description = f"""
        Rank: {role.mention}
        Level: **`{lvl}`**
        Experience: **`{exp}`**

        You currently the `{percentile:.2f}%` percetile of all members!
        ```py\n{scoreboard_s}```"""

        embed.color = discord.Color.from_str("#a2dcf7")

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Experience(bot))
