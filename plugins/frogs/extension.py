"""Frogs plugin extension — profile, register/configure spawns, catalog,
owner commands."""

from math import trunc

import hikari
import lightbulb
import pendulum

from core import leaderboard, timeparse, utils
from core.bot import CazzuBot
from core.errors import UserInputError
from core.models import FrogItemKey, FrogState
from core.tips import get_tip
from core.window import command_window, window_success

from plugins.misc.asset import random_footer_icon

from . import db as frog_db
from . import factory
from .species import SPECIES, Species

loader = lightbulb.Loader()

_COLOR = hikari.Color.from_hex_code("#a2dcf7")

# the collection book's undiscovered slot — a nameless placeholder: no
# species name, no description, no art, so a slot shows that something is
# still out there without spoiling what
_SILHOUETTE = "???"
_UNDISCOVERED = "Not yet discovered."
_EMPTY_STATE = (
    "You haven't discovered any frogs yet — catch one to fill a slot."
)

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
    description="Your discovered frog collection.",
):
    """Your discovered frog collection."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the invoker's collection book.

        Only the species the invoker has ever captured render with their
        name, art and description — discovery is lifetime (the capture log
        via ``frog_db.discovered_species``), so the book is a museum, not
        the current holdings. Every other non-hidden species renders as a
        nameless silhouette slot, and ``Species.hidden`` species take no
        slot at all. Nothing here names rarity, exp, weights, or how many
        species exist: the full set is staff-only (``/frog_catalog``).
        Entries are H3 markdown headers carrying the species name — Discord renders headings only in the description (not in
        field names/values), so the book carries no fields. The footer
        cycles a random frog tip, like /frog view's.
        """
        bot = utils.bot_from(ctx)
        user = ctx.member or ctx.user
        if not SPECIES:
            await ctx.respond("The frog catalog is empty.")
            return
        discovered = await frog_db.discovered_species(bot.db, user.id)
        sections: list[str] = []
        for species in SPECIES:
            if species.hidden:
                continue
            if species.key in discovered:
                sections.append(await _species_section(bot, species))
            else:
                sections.append(f"### {_SILHOUETTE}\n{_UNDISCOVERED}")
        body = "\n".join(sections)
        if not discovered:
            # zero captures: the empty state leads, and the silhouettes
            # stay — the book shows its shape even before the first catch
            body = f"{_EMPTY_STATE}\n\n{body}"
        embed = hikari.Embed(
            title=f"{user.display_name}'s Frog Collection",
            description=body,
            color=_COLOR,
        )
        await _set_frog_footer(embed, bot)
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


@loader.command()
class FrogCatalog(
    lightbulb.SlashCommand,
    name="frog_catalog",
    description="Render the full frog species set (staff asset check).",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
    hooks=[utils.ADMIN_ONLY],
):
    """The full species set — the staff-only counterpart of the book.

    Top-level rather than a ``/frog`` subcommand on purpose: lightbulb
    ignores ``default_member_permissions`` on subcommands (it warns at
    load), so a view hidden from members has to be its own top-level
    command — that field is what keeps it out of their picker, while the
    ``ADMIN_ONLY`` hook blocks execution if it is invoked anyway. Unlike
    ``/frog catalog`` (the per-member collection book) this renders EVERY
    species — including ``Species.hidden`` ones — because its job is
    verifying that each species' art publishes and renders, not
    collecting.
    """

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render every species — name, art, description."""
        bot = utils.bot_from(ctx)
        if not SPECIES:
            await ctx.respond("The frog catalog is empty.")
            return
        sections = [
            await _species_section(bot, species) for species in SPECIES
        ]
        embed = hikari.Embed(
            title="Frog Species Catalog",
            description="\n".join(sections),
            color=_COLOR,
        )
        await _set_frog_footer(embed, bot)
        await ctx.respond(embed=embed)


async def _inventory_glyph(
    bot: "CazzuBot", species_key: FrogItemKey
) -> str:
    """The inventory icon glyph for one normal frog (view snippet).

    The /frog view Inventory snippet lists frogs by their icon asset
    instead of the species name, mirroring /inventory view: a published
    ``icon_asset`` resolves through ``bot.assets.get`` to its
    custom-emoji reference (``<:name:id>``); while unpublished (no asset
    guild configured or a pending re-sync) the item's static ``icon`` is
    the fallback, so a line never renders "None". An unknown species
    (no registered item) degrades to the neutral frog icon — defensive;
    inventory rows only carry registered species.
    """
    item = bot.items.item_for(f"frog:{species_key.value}:normal")
    if item.icon_asset is not None:
        published = await bot.assets.get(item.icon_asset)
        if published is not None:
            return published
    return item.icon or "🐸"


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
    (normal) frogs only — each line lists the frog by its icon asset
    (published custom emoji; the species name is not shown), sorted by
    quantity ascending — frozen trophies and any future non-frog items
    are excluded.
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
        glyph = await _inventory_glyph(bot, species_key)
        inv_lines.append(f"• {glyph} ×`{qty}`")
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
    # the shared frog-tip footer (same cycling tip + random cirno icon as
    # the catalog surfaces — see _set_frog_footer)
    await _set_frog_footer(embed, bot)
    embed.description = f"""
		Total Frogs Captured: **`{user_frog_cnt}`**

		**__Inventory__**
		{inv_text}

		You are currently the `{utils.ordinal(trunc(percentile))}` percentile of all members!
		```py\n{scoreboard_s}```
		"""
    return embed


async def _species_section(bot: CazzuBot, species: Species) -> str:
    """One full catalog entry: an H3 name header, then art + description.

    The art resolves through ``bot.assets.get`` — a custom-emoji
    reference once published, ``None`` while unpublished, in which case
    the description stands alone rather than rendering "None".
    Undiscovered species never reach this helper: the collection book
    renders their silhouette slot instead, so they are never named,
    described, or given art.
    """
    art = (
        await bot.assets.get(species.art)
        if species.art is not None
        else None
    )
    body = f"{art} {species.description}" if art else species.description
    return f"### {species.name}\n{body}"


async def _set_frog_footer(embed: hikari.Embed, bot: CazzuBot) -> None:
    """Attach the cycling frog-tip footer + random cirno icon.

    Shared by the frog surfaces that carry a tip footer (``/frog view``,
    the collection book, the staff full-set view): the tip strings live in
    this plugin's own ``tip_sets`` (context "frog") and the icon pulls a
    random cirno emoji from the shared misc assets
    (``plugins.misc.asset`` — the tip surfaces' icon provider).
    """
    embed.set_footer(
        text=get_tip("frog"),
        icon=await random_footer_icon(bot),
    )
