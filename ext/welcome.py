"""Welcoming functionality for new users who join the server."""

import copy
import json
import logging
from typing import TYPE_CHECKING

import discord
import pendulum
from asyncpg import Record
from discord.ext import commands

from main import CazzuBot
from src import db, levels_helper, user_json, utility, welcome


_log = logging.getLogger(__name__)


class Welcome(commands.Cog):
    def __init__(self, bot: CazzuBot):
        self.bot = bot

    async def cog_command_error(self, ctx: commands.Context, err: Exception) -> None:
        if isinstance(err, commands.errors.MissingPermissions):
            return
        if isinstance(err, commands.BadArgument):
            pass

        raise err

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Welcome said user.

        Checking for pending seems to at times welcome a member multiple times in
        quick succession. This would imply that this method is being called several
        times, each with before and after having different pendings (duh). But as to
        why this happens, no idea.

        If completed_onboarding still triggers multiple welcomess, the next option is to
        use an internal cache and not welcome users who are already in the cache.
        """
        # if before.pending != after.pending:
        if before.flags.completed_onboarding != after.flags.completed_onboarding:
            guild = before.guild
            gid = guild.id

            enabled, cid, message, default_rid = (
                await db.welcome.get_payload(self.bot.pool, gid)
            ).values()

            # Verify valid settings
            if not enabled:
                return

            if not cid:
                msg = "Channel is not set or does not exist."
                raise self.WelcomeMisconfigutationError(msg)

            channel = guild.get_channel(cid)
            if not channel and cid:  # cid defined but channel not found
                msg = "Channel was set but was not found in guild."
                raise self.WelcomeMisconfigutationError(msg)

            role = guild.get_role(default_rid)
            if not role and default_rid:  # rid defined but role not found
                msg = "Default role was set but was not found in guild."
                raise self.WelcomeMisconfigutationError(msg)

            decoded = self.bot.json_decoder.decode(message)
            utility.deep_map(decoded, welcome.formatter, member=after)
            content, embed, embeds = user_json.prepare(decoded)
            await channel.send(content, embed=embed, embeds=embeds)

            if role:
                await after.add_roles(role)

    class WelcomeMisconfigutationError(Exception):
        """Raised when guild configuations are invalid."""

    @commands.group()
    @commands.has_permissions(administrator=True)
    async def welcome(self, ctx: commands.Context):
        """Entry command for welcome settings."""

    @welcome.group(name="set")
    async def welcome_set(self, ctx: commands.Context):
        """Set command entry."""

    @welcome_set.command(name="enabled")
    async def welcome_set_enabled(self, ctx: commands.Context, enabled: bool):
        """Enables welcoming or not."""
        gid = ctx.guild.id
        await db.welcome.set_enabled(self.bot.pool, gid, enabled)

    @welcome_set.command(name="verify")
    async def welcome_set_verify_first(self, ctx: commands.Context, verify_first: bool):
        """Denotes whether a user must first verify to be welcomed."""
        gid = ctx.guild.id
        await db.welcome.set_verify_first(self.bot.pool, gid, verify_first)

    @welcome_set.command(name="role")
    async def welcome_set_rid(self, ctx: commands.Context, role: discord.Role):
        """The role to alter when the user is welcomed."""
        gid = ctx.guild.id
        rid = role.id
        await db.welcome.set_default_rid(self.bot.pool, gid, rid)

    @welcome_set.command(name="channel")
    async def welcome_set_cid(
        self, ctx: commands.Context, channel: discord.TextChannel
    ):
        """The channel to welcome the user in."""
        gid = ctx.guild.id
        cid = channel.id
        await db.welcome.set_cid(self.bot.pool, gid, cid)

    @welcome_set.command(name="message", aliases=["msg"])
    async def welcome_set_message(self, ctx: commands.Context, *, message: str):
        """Set what the welcome message is to look like; supports embed.

        Takes a json object with placeholders for user mention or name.

        Consider seeing https://message.style/ for an interactive embed generator.
        or discohook.org
        Note that content AND embed must be present.
        MAKE SURE YOU USE CHANNEL EMBED, NOT WEBHOOK!
        """
        decoded = await user_json.verify(
            self.bot, ctx, message, welcome.formatter, member=ctx.author
        )

        gid = ctx.guild.id
        await db.welcome.set_message(
            self.bot.pool,
            gid,
            self.bot.json_encoder.encode(decoded),
        )

    @welcome.command(name="demo")
    async def welcome_demo(self, ctx: commands.Context):
        """Demos the welcome message in this channel with you as the new user."""
        gid = ctx.guild.id
        payload = await db.welcome.get_message(self.bot.pool, gid)
        decoded: dict = self.bot.json_decoder.decode(payload)

        member = ctx.author
        utility.deep_map(decoded, welcome.formatter, member=member)

        content, embed, embeds = user_json.prepare(decoded)
        await ctx.send(content, embed=embed, embeds=embeds)


async def setup(bot: CazzuBot):
    await bot.add_cog(Welcome(bot))
