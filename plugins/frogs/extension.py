"""Frogs plugin extension — profile, register/configure spawns, catalog,
owner commands."""

import json
from math import trunc

import hikari
import lightbulb
import pendulum

from cazzubot import leaderboard, templates, timeparse, utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.models import FrogState, FrogItemKey
from cazzubot.window import command_window, window_success

from . import db as frog_db
from . import factory
from .items import frog_exp
from .species import SPECIES, by_key

loader = lightbulb.Loader()

_SCOREBOARD_STAMP = (
    "https://cdn.discordapp.com/emojis/752290769712316506.webp"
    "?size=160&quality=lossless"
)
_COLOR = hikari.Color.from_hex_code("#a2dcf7")

_SPECIES_CHOICES = [
    lightbulb.Choice(species.name, species.key.value)
    for species in SPECIES
]

frog = lightbulb.Group("frog", "Frog species economy.")


def _species_option(
    name: str = "species", description: str = "The frog species"
):
    return lightbulb.string(
        name, description, default=None, choices=_SPECIES_CHOICES
    )


def _species_key(value: str | None) -> FrogItemKey | None:
    """Parse a slash option's species string; None rolls at spawn."""
    if value is None:
        return None
    try:
        return FrogItemKey(value)
    except ValueError as err:
        raise UserInputError(f"Unknown frog species: {value}") from err


@frog.register
class Profile(
    lightbulb.SlashCommand,
    name="profile",
    description="Show this user's current frog profile.",
):
    """Show a user's current frog profile."""

    member = lightbulb.user("member", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the seasonal frog profile embed."""
        bot = utils.bot_from(ctx)
        target = self.member or ctx.member or ctx.user
        now = pendulum.now("UTC")
        rows = await frog_db.seasonal_ranked(
            bot.db, now.year, utils.month2season(now.month)
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
class Catalog(
    lightbulb.SlashCommand,
    name="catalog",
    description="Browse the catchable frog species.",
):
    """Browse the catchable frog species."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the species catalog embed."""
        bot = utils.bot_from(ctx)
        if not SPECIES:
            await ctx.respond("The frog catalog is empty.")
            return
        embed = hikari.Embed(title="Frog Species Catalog", color=_COLOR)
        # thumbnail: the first species with published art wins the slot
        thumbnail_art: str | None = None
        for species in SPECIES:
            if thumbnail_art is None:
                thumbnail_art = await bot.assets.get(species.art)
                if thumbnail_art is not None:
                    embed.set_thumbnail(thumbnail_art)
            value = f"{species.description}\nRarity: {species.rarity}"
            # consumption is item-owned — the catalog reports each species'
            # consume value from its item definitions (per-state)
            normal_exp = frog_exp(species.key, FrogState.NORMAL)
            frozen_exp = frog_exp(species.key, FrogState.FROZEN)
            value += (
                f"\nConsume: **`{normal_exp}`** exp (normal) / "
                f"**`{frozen_exp}`** exp (frozen)"
            )
            embed.add_field(
                name=f"{species.name} (`{species.key.value}`)", value=value
            )
        await ctx.respond(embed=embed)


@frog.register
class Lifetime(
    lightbulb.SlashCommand,
    name="lifetime",
    description="Lifetime frog profile variant.",
):
    """Lifetime frog profile variant."""

    user = lightbulb.user("user", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the lifetime frog profile embed."""
        bot = utils.bot_from(ctx)
        target = self.user or ctx.member or ctx.user
        rows = await frog_db.lifetime_ranked(bot.db)
        if not rows:
            await ctx.respond(
                "No one has yet captured frogs in this server!"
            )
            return
        if target.id not in [r[1] for r in rows]:
            await ctx.respond("You have not yet captured any frogs!")
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
    hooks=[utils.ADMIN_ONLY],
):
    """Register this channel as a frog spawn channel."""

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
        bot = utils.bot_from(ctx)
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
    hooks=[utils.ADMIN_ONLY],
):
    """Remove all frog settings and stop frog spawning."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Clear spawn configs and drop the spawn tasks."""
        bot = utils.bot_from(ctx)
        await frog_db.clear_spawns(bot.db)
        await bot.scheduler.drop_tag("frog")
        await window_success(ctx, "Cleared all frog spawn channels")


frog_set = frog.subgroup("set", "Configure frog spawns.")


@frog_set.register
class SetMessage(
    lightbulb.SlashCommand,
    name="message",
    description="Set the capture message JSON.",
    hooks=[utils.ADMIN_ONLY],
):
    """Set the capture message JSON."""

    message = lightbulb.string("message", "The capture message JSON")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Validate and persist the capture message JSON."""
        bot = utils.bot_from(ctx)
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
    hooks=[utils.ADMIN_ONLY],
):
    """Enable or disable frog spawns."""

    val = lightbulb.boolean("val", "Whether frog spawning is enabled")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Persist the flag and re-queue or clear the spawn tasks."""
        bot = utils.bot_from(ctx)
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
    hooks=[utils.ADMIN_ONLY],
):
    """Preview the capture message as the invoker."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the stored capture message as a preview."""
        bot = utils.bot_from(ctx)
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
    hooks=[utils.ADMIN_ONLY],
):
    """Dump the raw stored capture message JSON."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Echo the stored capture message JSON verbatim."""
        bot = utils.bot_from(ctx)
        msg_json = await frog_db.get_message(bot.settings)
        await ctx.respond(f"```{json.dumps(msg_json, indent=2)}```")


async def _spawn_and_wait(
    bot: CazzuBot, ctx: lightbulb.Context, species_value: str | None
) -> None:
    """Force-post a frog with its capture button (shared by spawn/fake)."""
    await factory.spawn_and_wait(
        bot,
        30,
        ctx,
        cid=ctx.channel_id,
        species_key=_species_key(species_value),
    )


@frog.register
class Spawn(
    lightbulb.SlashCommand,
    name="spawn",
    description="Force-spawn a frog in this channel.",
    hooks=[utils.OWNER_ONLY],
):
    """Force-spawn a frog in this channel."""

    species = _species_option(
        "species", "The species to spawn (default: rolled)"
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Post a spawned frog with its capture button."""
        # the frog message is the success signal — no separate confirmation
        await _spawn_and_wait(utils.bot_from(ctx), ctx, self.species)


@frog.register
class Fake(
    lightbulb.SlashCommand,
    name="fake",
    description="Post a fake frog with its capture button.",
    hooks=[utils.OWNER_ONLY],
):
    """Post a fake frog with its capture button."""

    species = _species_option(
        "species", "The species to fake (default: rolled)"
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Post a fake frog with its capture button."""
        await _spawn_and_wait(utils.bot_from(ctx), ctx, self.species)


@frog.register
class Resync(
    lightbulb.SlashCommand,
    name="resync",
    description="Rebuild lifetime capture counts from the frog logs.",
    hooks=[utils.OWNER_ONLY],
):
    """Rebuild lifetime capture counts from the frog logs."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Confirm, then rebuild lifetime captures from the logs."""
        bot = utils.bot_from(ctx)
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
    board = await leaderboard.focus_board(
        bot,
        rows,
        user.id,
        headers=["Rank", "Frogs", "User"],
        align=["<", ">", ">"],
        max_padding=[0, 0, 16],
    )
    # the callers (Profile/Lifetime) verified membership first
    assert board is not None
    scoreboard_s = board.text
    user_frog_cnt = board.value
    rank = board.rank

    inv = await frog_db.inventory_rows(bot.db, user.id)
    inv_lines = []
    for species_key, state, qty in inv:
        species = by_key(species_key)
        label = species.name if species is not None else species_key.value
        inv_lines.append(f"{label} ({state.value}): **`{qty}`**")
    inv_text = "\n".join(inv_lines) if inv_lines else "No frogs yet."

    now = pendulum.now("UTC")
    if lifetime:
        total = await frog_db.total_members(bot.db)
    else:
        total = await frog_db.seasonal_total_members(
            bot.db, now.year, utils.month2season(now.month)
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
		{inv_text}

		You are currently the `{utils.ordinal(trunc(percentile))}` percentile of all members!
		```py\n{scoreboard_s}```
		"""
    return embed
