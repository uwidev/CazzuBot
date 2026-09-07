"""Frogs plugin extension — profile, register/configure spawns, catalog,
owner commands."""

from math import trunc

import hikari
import lightbulb
import pendulum

from cazzubot import leaderboard, timeparse, utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.models import FrogItemKey, FrogState
from cazzubot.tips import get_tip
from cazzubot.window import command_window, window_success

from plugins.misc.asset import random_footer_icon

from . import db as frog_db
from . import factory
from .species import SPECIES, by_key

loader = lightbulb.Loader()

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
class View(
    lightbulb.SlashCommand,
    name="view",
    description="Show a user's frog capture permit.",
):
    """Show a user's seasonal or lifetime frog capture permit."""

    member = lightbulb.user("member", "The member to show", default=None)
    mode = lightbulb.string(
        "mode",
        "The permit window",
        default="seasonal",
        choices=[
            lightbulb.Choice("Seasonal", "seasonal"),
            lightbulb.Choice("Lifetime", "lifetime"),
        ],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the frog capture permit for the chosen window."""
        bot = utils.bot_from(ctx)
        target = self.member or ctx.member or ctx.user
        lifetime = self.mode == "lifetime"
        if lifetime:
            rows = await frog_db.lifetime_ranked(bot.db)
        else:
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
                "You have not yet captured any frogs!"
                if lifetime
                else "You have not yet captured any frogs this season!"
            )
            return
        await ctx.respond(
            embed=await _prepare_personal_summary(
                bot, ctx, target, rows, lifetime=lifetime
            )
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
        """Render the species catalog embed — name, art, description.

        Each field shows the species' published art (emoji reference when
        published) and its description only — what catching or consuming
        the frog does belongs to the item's own info card, not here. The
        footer cycles a random frog tip, like /frog view's.
        """
        bot = utils.bot_from(ctx)
        if not SPECIES:
            await ctx.respond("The frog catalog is empty.")
            return
        embed = hikari.Embed(title="Frog Species Catalog", color=_COLOR)
        for species in SPECIES:
            art = (
                await bot.assets.get(species.art)
                if species.art is not None
                else None
            )
            value = (
                f"{art} {species.description}"
                if art
                else species.description
            )
            # species name is bolded as the field label — the catalog is a
            # recap of owned frogs, so names read as entries, not nav links
            embed.add_field(name=f"**{species.name}**", value=value)
        # cycle one random frog tip through the footer per render — the tip
        # sets live in this plugin's own tip_sets (context "frog"), shared
        # with /frog view, and the footer icon pulls a random cirno emoji
        # from the shared misc assets (plugins.misc.asset — the tip surfaces'
        # icon provider)
        embed.set_footer(
            text=get_tip("frog"),
            icon=await random_footer_icon(bot),
        )
        await ctx.respond(embed=embed)


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


async def _spawn_and_wait(
    bot: CazzuBot, ctx: lightbulb.Context, species_value: str | None
) -> None:
    """Force-post a frog with its capture button (the spawn command)."""
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


frog_debug = frog.subgroup("debug", "Owner debug helpers.")


@frog_debug.register
class DebugFreeze(
    lightbulb.SlashCommand,
    name="freeze",
    description="Run the quarterly rollover (freeze) for one user.",
    hooks=[utils.OWNER_ONLY],
):
    """Freeze one user's frogs in place — a dry-run of the season reset.

    The debug counterpart to the scheduler's global
    ``db.season_reset_frogs`` (which freezes EVERY user): this scopes the
    same per-species ``normal -> frozen`` move to one member via
    ``db.freeze_frogs_for_user``, so the owner can inspect the frozen
    state on the frog + inventory surfaces without waiting for the real
    rollover.
    """

    member = lightbulb.user("member", "The member to freeze")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Freeze the member's frogs and report what moved."""
        bot = utils.bot_from(ctx)
        moved = await frog_db.freeze_frogs_for_user(bot.db, self.member.id)
        if not moved:
            await window_success(
                ctx,
                f"{self.member.display_name} has no normal frogs to freeze.",
            )
            return
        names = {species.key: species.name for species in SPECIES}
        detail = ", ".join(f"{names[key]} ×{qty}" for key, qty in moved)
        await window_success(
            ctx,
            f"Froze {self.member.display_name}'s frogs: {detail}",
        )


loader.command(frog)


async def _prepare_personal_summary(
    bot: CazzuBot,
    ctx: lightbulb.Context,
    user: hikari.User | hikari.Member,
    rows: list[tuple[int, int, int]],
    *,
    lifetime: bool = False,
) -> hikari.Embed:
    """The "Frog Capture Permit" embed — the permit title carries the
    member's name (no author field), the pfp is the thumbnail, and the
    footer cycles a random frog tip.

    Its Inventory section is a snippet of the member's season-active
    (normal) frogs only, sorted by quantity ascending (frozen trophies and
    any future non-frog items are excluded) — see the inline build below.
    """
    board = await leaderboard.focus_board(
        bot,
        rows,
        user.id,
        headers=["Rank", "Frogs", "User"],
        align=["<", ">", ">"],
        max_padding=[0, 0, 16],
    )
    # the callers (View's seasonal/lifetime modes) verified membership first
    assert board is not None
    scoreboard_s = board.text
    user_frog_cnt = board.value
    rank = board.rank

    # Inventory snippet: only normal (season-active) frogs, quantity
    # ascending, frog-type only. ``inventory_rows`` already narrows to the
    # "frog:" namespace (future non-frog items stay out), so the explicit
    # state filter below is the remaining frog-type guard. Frozen frogs are
    # trophies, not frogs the member "currently has", so they stay out of
    # the snippet and do not suppress the "No frogs yet." empty state.
    inv = await frog_db.inventory_rows(bot.db, user.id)
    inv_lines = []
    for species_key, state, qty in sorted(
        (
            (species_key, state, qty)
            for species_key, state, qty in inv
            if state is FrogState.NORMAL
        ),
        key=lambda row: row[2],
    ):
        species = by_key(species_key)
        label = species.name if species is not None else species_key.value
        inv_lines.append(f"• {label} ×`{qty}`")
    inv_text = "\n".join(inv_lines) if inv_lines else "No frogs yet."

    now = pendulum.now("UTC")
    if lifetime:
        total = await frog_db.total_members(bot.db)
    else:
        total = await frog_db.seasonal_total_members(
            bot.db, now.year, utils.month2season(now.month)
        )

    percentile = utils.calc_percentile(rank, total)

    embed = hikari.Embed(
        title=f"{user.display_name}'s Frog Capture Permit", color=_COLOR
    )
    embed.set_thumbnail(str(user.display_avatar_url))
    # cycle one random frog tip through the footer per render — the tip
    # sets live in this plugin's own tip_sets (context "frog"), shared with
    # /frog catalog, and the footer icon pulls a random cirno emoji from the
    # shared misc assets (plugins.misc.asset — the tip surfaces' icon provider)
    embed.set_footer(
        text=get_tip("frog"),
        icon=await random_footer_icon(bot),
    )
    embed.description = f"""
		Total Frogs Captured: **`{user_frog_cnt}`**

		**__Inventory__**
		{inv_text}

		You are currently the `{utils.ordinal(trunc(percentile))}` percentile of all members!
		```py\n{scoreboard_s}```
		"""
    return embed
