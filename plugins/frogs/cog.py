"""Frogs plugin extension — profile, register/configure spawns, consume,
owner commands."""

import asyncio
import json
from math import trunc
from typing import Any, cast

import hikari
import lightbulb
import pendulum

from cazzubot import leaderboard, templates, timeparse, utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.models import FrogTypeEnum, MemberExpLogSourceEnum
from cazzubot.window import command_window, window_success
from lightbulb.prefab import checks as prefab_checks

from . import db as frog_db
from . import factory
from .logic import (
    consume_total_exp,
    ensure_consume_amount,
    exp_per_frog,
)

loader = lightbulb.Loader()

_SCOREBOARD_STAMP = (
    "https://cdn.discordapp.com/emojis/752290769712316506.webp"
    "?size=160&quality=lossless"
)
_COLOR = hikari.Color.from_hex_code("#a2dcf7")

frog = lightbulb.Group("frog", "Frog token economy.")

_OWNER = prefab_checks.owner_only
_ADMIN = prefab_checks.has_permissions(hikari.Permissions.ADMINISTRATOR)


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


def _frog_type_option(
    name: str = "frog_type", description: str = "The frog type"
):
    return lightbulb.string(
        name,
        description,
        default="normal",
        choices=[
            lightbulb.Choice("Normal", "normal"),
            lightbulb.Choice("Frozen", "frozen"),
        ],
    )


@frog.register
class Profile(
    lightbulb.SlashCommand,
    name="profile",
    description="Show this user's current frog profile.",
):
    member = lightbulb.user("member", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        target = self.member or ctx.member or ctx.user
        now = pendulum.now("UTC")
        rows = await frog_db.seasonal_ranked(
            bot.db, now.year, (now.month - 1) // 3
        )
        if not rows:
            await ctx.respond(
                "No one has yet captured frogs in this server!"
            )
            return
        if target.id not in [r[1] for r in rows]:
            await ctx.respond(
                "You have not yet captured any frogs this season!"
            )
            return
        await ctx.respond(
            embed=await _prepare_personal_summary(bot, ctx, target, rows)
        )


@frog.register
class Consume(
    lightbulb.SlashCommand,
    name="consume",
    description="Consume frogs for seasonal experience (10 exp normal / 3 frozen).",
):
    amount = lightbulb.integer(
        "amount", "How many frogs to consume", default=1, min_value=1
    )
    frog_type = _frog_type_option()

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        uid = (ctx.member or ctx.user).id
        frog_type = FrogTypeEnum(self.frog_type)
        balance = await frog_db.get_frogs(bot.db, uid, frog_type)
        ensure_consume_amount(self.amount, balance)

        exp_per = exp_per_frog(frog_type)
        total_exp = consume_total_exp(frog_type, self.amount)
        now = pendulum.now("UTC")

        from plugins.experience.db import seasonal_exp

        exp_old = await seasonal_exp(
            bot.db, uid, now.year, (now.month - 1) // 3
        )

        desc = (
            f"You are about to consume **`{self.amount}` "
            f"{frog_type.value} frog(s)**.\n\n"
            f"These types of frogs grant `{exp_per}` exp per frog, for a "
            f"total of **`{total_exp}`**.\n\n"
            f"Resulting frogs\n**`{balance}`** -> "
            f"**`{balance - self.amount}`**\n"
            f"Resulting exp\n**`{exp_old:,}`** -> "
            f"**`{exp_old + total_exp:,}`**\n\n"
            "Please confirm."
        )
        embed = utils.prepare_embed("**Confirmation**", desc)
        embed.set_thumbnail("https://i.imgur.com/ybxI7pu.png")

        menu = utils.ConfirmMenu(uid, delete_after=False)
        await ctx.respond(embed=embed, components=cast(Any, menu))
        try:
            await menu.attach(ctx.client, timeout=120)
        except asyncio.TimeoutError:
            await ctx.delete_response(utils.INITIAL_RESPONSE_IDENTIFIER)
            return
        if not menu.value:
            await ctx.delete_response(utils.INITIAL_RESPONSE_IDENTIFIER)
            return

        # re-check balance at the very moment of consumption
        balance_now = await frog_db.get_frogs(bot.db, uid, frog_type)
        ensure_consume_amount(self.amount, balance_now)

        now = pendulum.now("UTC")
        from plugins.experience.db import add_exp_log

        await add_exp_log(
            bot.db,
            uid,
            total_exp,
            now,
            source=MemberExpLogSourceEnum.FROG,
        )
        await frog_db.modify_frog(
            bot.db, uid, modify=-self.amount, frog_type=frog_type
        )

        embed_post = utils.prepare_embed(
            "Frog(s) have been consumed!",
            f"Resulting {frog_type.value} frogs\n"
            + f"**`{balance}`** -> **`{balance - self.amount}`**",
        )
        embed_post.set_thumbnail("https://i.imgur.com/kCHjymJ.png")
        await ctx.edit_response(
            utils.INITIAL_RESPONSE_IDENTIFIER, embed=embed_post
        )


@frog.register
class Lifetime(
    lightbulb.SlashCommand,
    name="lifetime",
    description="Lifetime frog profile variant.",
):
    user = lightbulb.user("user", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        target = self.user or ctx.member or ctx.user
        rows = await frog_db.lifetime_ranked(bot.db)
        if not rows:
            await ctx.respond(
                "No one has yet captured frogs in this server!"
            )
            return
        if target.id not in [r[1] for r in rows]:
            await ctx.respond(
                "You have not yet captured any frogs!"
            )
            return
        await ctx.respond(
            embed=await _prepare_personal_summary(
                bot, ctx, target, rows, lifetime=True
            )
        )


@frog.register
class Register(
    lightbulb.SlashCommand,
    name="register",
    description="Register this channel as a frog spawn channel.",
    hooks=[_ADMIN],
):
    interval = lightbulb.string(
        "interval", "Time between spawns (natural duration)"
    )
    persist = lightbulb.string(
        "persist", "Seconds a frog stays until disappearing", default="30"
    )
    fuzzy = lightbulb.number(
        "fuzzy", "Randomness of spawn intervals (0-1)", default=0.5
    )
    channel = lightbulb.channel(
        "channel",
        "The spawn channel (default: this channel)",
        default=None,
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Register this channel as a frog spawn channel.

        Interval uses natural duration processing, at least 1 frog every
        interval. Persist is in seconds, how many seconds a frog stays until
        disappearing. Fuzzy is a decimal percent, the randomness of spawning
        intervals.
        """
        bot = _bot(ctx)
        cid = (
            self.channel.id if self.channel is not None else ctx.channel_id
        )

        try:
            interval_s = timeparse.parse_duration(
                self.interval
            ).in_seconds()
        except timeparse.InvalidTimeError as err:
            raise UserInputError(
                f"Interval {self.interval} is not a valid time."
            ) from err

        if not bot.config.debug and interval_s < 60:
            raise UserInputError(
                "Interval must be greater than 60 seconds."
            )

        try:
            persist_s = timeparse.parse_duration(self.persist).in_seconds()
        except timeparse.InvalidTimeError as err:
            raise UserInputError(
                f"Persist {self.persist} is not a valid time."
            ) from err

        if not bot.config.debug and not 3 <= persist_s <= 120:
            raise UserInputError(
                "Persist must be between 3 and 120 seconds."
            )
        if not bot.config.debug and not 0 <= self.fuzzy <= 1:
            raise UserInputError("Fuzzy must be between 0 and 1.")

        await frog_db.upsert_spawn(
            bot.db, cid, interval_s, persist_s, self.fuzzy
        )
        await factory.reset_frog_tasks(bot)
        await window_success(ctx, "Spawn channel registered")


@frog.register
class Clear(
    lightbulb.SlashCommand,
    name="clear",
    description="Remove all frog settings and stop frog spawning.",
    hooks=[_ADMIN],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await frog_db.clear_spawns(bot.db)
        await bot.scheduler.drop_tag("frog")
        await window_success(ctx, "Cleared all frog spawn channels")


frog_set = frog.subgroup("set", "Configure frog spawns.")


@frog_set.register
class SetMessage(
    lightbulb.SlashCommand,
    name="message",
    description="Set the capture message JSON.",
    hooks=[_ADMIN],
):
    message = lightbulb.string("message", "The capture message JSON")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        decoded = templates.verify(
            self.message,
            factory.formatter,
            member=utils.member_snapshot(ctx.member or ctx.user),
        )
        await frog_db.set_message(bot.settings, decoded)
        await window_success(ctx, "Capture message set")


@frog_set.register
class SetEnabled(
    lightbulb.SlashCommand,
    name="enabled",
    description="Enable/disable frog spawns (re-queues or clears spawn tasks).",
    hooks=[_ADMIN],
):
    val = lightbulb.boolean("val", "Whether frog spawning is enabled")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await frog_db.set_enabled(bot.settings, self.val)
        await factory.reset_frog_tasks(bot)
        await window_success(
            ctx,
            "Frog spawning enabled"
            if self.val
            else "Frog spawning disabled",
        )


@frog.register
class Demo(
    lightbulb.SlashCommand,
    name="demo",
    description="Preview the capture message as yourself.",
    hooks=[_ADMIN],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        msg_json = await frog_db.get_message(bot.settings)
        if not msg_json:
            await ctx.respond("No capture message has been set.")
            return
        utils.deep_map(
            msg_json,
            factory.formatter,
            member=utils.member_snapshot(ctx.member or ctx.user),
        )
        await templates.send(ctx, msg_json)


@frog.register
class Raw(
    lightbulb.SlashCommand,
    name="raw",
    description="Dump the raw stored capture message JSON.",
    hooks=[_ADMIN],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        msg_json = await frog_db.get_message(bot.settings)
        await ctx.respond(f"```{json.dumps(msg_json, indent=2)}```")


@frog.register
class Spawn(
    lightbulb.SlashCommand,
    name="spawn",
    description="Force-spawn a frog in this channel.",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        # the frog message is the success signal — no separate confirmation
        await factory.spawn_and_wait(bot, 30, ctx, cid=ctx.channel_id)


@frog.register
class Fake(
    lightbulb.SlashCommand,
    name="fake",
    description="Post a fake frog with its capture button.",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await factory.spawn_and_wait(bot, 30, ctx, cid=ctx.channel_id)


@frog.register
class Resync(
    lightbulb.SlashCommand,
    name="resync",
    description="Rebuild lifetime capture counts from the frog logs.",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        if not await utils.author_confirm(ctx):
            return
        async with command_window(ctx) as window:
            window.info("Fetching frog logs...")
            await window.flush()  # ack early before the big UPDATE
            await frog_db.sync_with_frog_logs(bot.db)
            window.success("Lifetime captures synced.")


loader.command(frog)


async def _prepare_personal_summary(
    bot: CazzuBot,
    ctx: lightbulb.Context,
    user: hikari.User | hikari.Member,
    rows: list[tuple[int, int, int]],
    *,
    lifetime: bool = False,
) -> hikari.Embed:
    """The "Frog Capture Permit" embed."""
    uid = user.id
    uids = [r[1] for r in rows]
    uid_index = uids.index(uid)
    subset, subset_i = leaderboard.create_focus_subset(rows, uid_index)

    ranks = [r[0] for r in subset]
    frog_cnt = [r[2] for r in subset]
    names: list[str] = []
    for uid_ in [r[1] for r in subset]:
        member = await utils.find_user(bot, uid_)
        names.append(utils.found_name(member, uid_))

    window = list(zip(ranks, frog_cnt, names))
    headers = ["Rank", "Frogs", "User"]
    align = ["<", ">", ">"]
    max_padding = [0, 0, 16]

    scoreboard = leaderboard.format(
        window, headers, align=align, max_padding=max_padding
    )
    col_widths = leaderboard.calc_max_col_width(
        window, headers, max_padding
    )
    leaderboard.highlight_row(scoreboard, subset_i, col_widths)
    scoreboard_s = "\n".join(scoreboard)

    user_frog_cnt = frog_cnt[subset_i]
    normal_inv = await frog_db.get_frogs(bot.db, uid, FrogTypeEnum.NORMAL)
    frozen_inv = await frog_db.get_frogs(bot.db, uid, FrogTypeEnum.FROZEN)
    rank = ranks[subset_i]

    now = pendulum.now("UTC")
    if lifetime:
        total = await frog_db.total_members(bot.db)
    else:
        total = await frog_db.seasonal_total_members(
            bot.db, now.year, (now.month - 1) // 3
        )

    percentile = utils.calc_percentile(rank, total)

    embed = hikari.Embed(color=_COLOR)
    embed.set_author(
        name=f"{user.display_name}'s Frog Capture Permit",
        icon=_SCOREBOARD_STAMP,
    )
    embed.set_thumbnail(str(user.display_avatar_url))
    embed.description = f"""
		Total Frogs Captured: **`{user_frog_cnt}`**

		**__Inventory__**
		Frogs (Seasonal): **`{normal_inv}`**
		Frogs (Frozen): **`{frozen_inv}`**

		You are currently the `{utils.ordinal(trunc(percentile))}` percentile of all members!
		```py\n{scoreboard_s}```
		"""
    return embed
