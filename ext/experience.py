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

from src import db, levels_helper


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

    def _calc_min_rank(self, rank_thresholds: list[Record], level) -> tuple[int, int]:
        """Naively determine rank based on level from list of records."""
        if level < rank_thresholds[0]["threshold"]:
            return None, None

        for i in range(1, len(rank_thresholds)):
            if level < rank_thresholds[i]["threshold"]:
                return rank_thresholds[i - 1]["rid"], i - 1

        return rank_thresholds[-1]["rid"], len(rank_thresholds) - 1

    async def _on_msg_handle_ranks(self, message: discord.Message, level: int):
        """Handle potential rank ups from level ups.

        Also keeps rank integrity regardless of level up.
        """
        ranks = await db.rank.get(self.bot.pool, message.guild.id)
        if not ranks:
            return

        rid, index = self._calc_min_rank(ranks, level)

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
