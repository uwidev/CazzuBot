"""Experience calculations and management.

See member_exp_log.py for details on how exp is stored and summed.
"""
import logging

import discord
import pendulum
from discord.ext import commands
from discord.ext.commands.context import Context

from src import db, levels_helper


_log = logging.getLogger(__name__)

# Global Variables for Experience rates
#
# These variables are never meant to be modified except through hard code.
# These variables, especially the cooldown and exp reset, are not changed upon cog reload at the moment.
# Im just having some some problems when it comes to cancelling a task and restarting it. Maybe in the future when I'm more used
# to tasks it might be feasible, but for now, if you ever need to change these values, it's best to restart the bot.
_EXP_BASE = 1
_EXP_BONUS_FACTOR = 20
_EXP_DECAY_UNTIL_BASE = 77
_EXP_DECAY_FACTOR = 2
_EXP_COOLDOWN = 15  # seconds
_EXP_BUFF_RESET = 1440  # mins    |   1440m = 24h


def _calc_exp(msg: int):
    """Return the bonus experience a user should expect given various factors."""
    return round(
        max(
            0,
            _EXP_BASE * _EXP_BONUS_FACTOR
            - _EXP_BASE
            - (_EXP_BASE * _EXP_BONUS_FACTOR - _EXP_BASE)
            * (msg / _EXP_DECAY_UNTIL_BASE) ** _EXP_DECAY_FACTOR,
        )
    )


# Used for to lookup later by levels.py to determine level threshold
RE_MIN_DURATION = _EXP_COOLDOWN * _EXP_DECAY_UNTIL_BASE / 60

# dict of message count to its rewarded exp, starting at 1
RE_MSG_EXP_CUMULATIVE = dict()
RE_MSG_EXP_CUMULATIVE[1] = _EXP_BASE + _calc_exp(0)

for i in range(2, _EXP_DECAY_UNTIL_BASE + 1):
    RE_MSG_EXP_CUMULATIVE[i] = (
        RE_MSG_EXP_CUMULATIVE[i - 1] + _EXP_BASE + _calc_exp(i - 1)
    )


class Experience(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Add experience to the member based on prior activity."""
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
        exp_gain = _EXP_BASE + _calc_exp(msg_cnt)
        new_exp = old_exp + exp_gain
        offset_cooldown = now + pendulum.duration(seconds=_EXP_COOLDOWN)

        _log.info("Granting %s exp to %s", exp_gain, message.author)
        # For guild lifetime
        member_updated = db.table.Member(gid, uid, new_exp, msg_cnt, offset_cooldown)
        await db.member.update_exp(self.bot.pool, member_updated)

        # For logging and leaderboard
        await db.member_exp_log.add(
            self.bot.pool, db.table.MemberExpLog(gid, uid, exp_gain, now)
        )

        # Calculations if level up
        old_level = levels_helper.level_from_exp(old_exp)
        new_level = levels_helper.level_from_exp(new_exp)

        if new_level > old_level:
            _log.info(
                f"{message.author} has leveled up from {old_level} to {new_level}!"
            )

    @commands.group(aliases=["xp"], invoke_without_command=True)
    async def exp(self, ctx: Context, *, user: discord.Member = None):
        """Show your experience points and the leaderboards."""
        if user is None:
            user = ctx.message.author

        uid = user.id
        gid = ctx.guild.id

        # this_user = await member_exp.get(self.bot.pool, gid, uid)
        all_users = await db.member.get_all_member_exp(self.bot.pool, gid)
        rank, exp = await db.member.get_rank_exp(self.bot.pool, gid, uid)

        # _log.info(f"{rank} || {exp}")
        # _log.info(f"{all_users=}")

        # title = f"{user.display_name}'s Club Membership Card"

        # rank_id = this_user["rank"]
        # rank = ctx.guild.get_role(rank_id)
        # level = this_user["level"]
        # exp = this_user["exp"]

        # data = (
        #     f"Rank: {rank.mention}\nLevel: **`{level}`**\nExperience: **`{int(exp)}`**"
        # )
        # report = "{user} are ranked **`#{place}`** out of **`{total}`**!".format(
        #     user="You" if ctx.message.author == user else user.mention,
        #     place=rank + 1,
        #     total=len(all_users),
        # )

        # compare = "```py\n{place:8}{mode:<8}{user:20}\n".format(
        #     place="Place", mode="Exp", user="User"
        # )
        # for i in range(max(0, rank - 2), min(rank + 3, len(all_users))):
        #     try:
        #         if i == rank:
        #             compare += "{place:.<8}{count:.<8}{user:20}\n".format(
        #                 place="@" + str(i + 1),
        #                 count=int(all_users[i]["exp"]),
        #                 user=self.bot.get_user(all_users[i]["id"]).display_name,
        #             )
        #         elif i % 2:
        #             compare += "{place:<8}{count:<8}{user:20}\n".format(
        #                 place=str(i + 1),
        #                 count=int(all_users[i]["exp"]),
        #                 user=self.bot.get_user(all_users[i]["id"]).display_name,
        #             )
        #         else:
        #             compare += "{place:.<8}{count:.<8}{user:20}\n".format(
        #                 place=str(i + 1),
        #                 count=int(all_users[i]["exp"]),
        #                 user=self.bot.get_user(all_users[i]["id"]).display_name,
        #             )
        #     except AttributeError:
        #         if i == rank:
        #             compare += "{place:.<8}{count:.<8}{user:20}\n".format(
        #                 place="@" + str(i + 1),
        #                 count=int(all_users[i]["exp"]),
        #                 user=(
        #                     await self.bot.fetch_user(all_users[i]["id"])
        #                 ).display_name,
        #             )
        #         elif i % 2:
        #             compare += "{place:<8}{count:<8}{user:20}\n".format(
        #                 place=str(i + 1),
        #                 count=int(all_users[i]["exp"]),
        #                 user=(
        #                     await self.bot.fetch_user(all_users[i]["id"])
        #                 ).display_name,
        #             )
        #         else:
        #             compare += "{place:.<8}{count:.<8}{user:20}\n".format(
        #                 place=str(i + 1),
        #                 count=int(all_users[i]["exp"]),
        #                 user=(
        #                     await self.bot.fetch_user(all_users[i]["id"])
        #                 ).display_name,
        #             )
        # compare += "```"

        # desc = data + "\n\n" + report + "\n" + compare

        # embed = make_simple_embed_t(title, desc)
        # embed.set_thumbnail(url=user.avatar_url)

        # await ctx.send(embed=embed)

        # # await ctx.send('Your current exp is **`{exp}`** with an exp factor of **`x{factor:.2f}`**.'.format(exp=int(exp), factor=factor))


async def setup(bot: commands.Bot):
    await bot.add_cog(Experience(bot))
