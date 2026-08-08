"""Counter plugin extension — baka button view, create command, expiry.

Single-guild port of v1's ``ext/counter.py``. A registered counter message
carries a persistent button; each press increments the count, the footer shows
who "did a baka", and a 2-hour expiry task (tag ``counter``) resets the footer.
The button is a plain component with a fixed custom id handled by a component-
interaction listener, so it survives restarts without re-registration.
"""

import logging
from typing import Any, cast

import hikari
import lightbulb
import pendulum

from cazzubot import utils
from cazzubot.bot import CazzuBot

from . import db

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

FROG = "https://files.catbox.moe/qo7bkv.gif"
POGFROG = "https://files.catbox.moe/k5qvvd.gif"
BAKAPPLE = "https://files.catbox.moe/og9q1l.gif"
BORED = "https://files.catbox.moe/0ex005.gif"
CIRNO_HELP = "<:cirnoHelp:695126168227151954>"

NO_BAKAS_TEXT = "There are no bakas as of recently..."

CUSTOM_ID = "counter:baka"


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


counter = lightbulb.Group("counter", "Baka counter management.")


@counter.register
class Create(
    lightbulb.SlashCommand,
    name="create",
    description="Create the baka counter message in this channel.",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        embed = utils.prepare_embed(
            "Number of times people have touched the baka button", "> 0"
        )
        embed.set_thumbnail(BORED)
        embed.set_footer(text=NO_BAKAS_TEXT, icon=FROG)
        row = hikari.impl.MessageActionRowBuilder().add_interactive_button(
            hikari.ButtonStyle.PRIMARY,
            CUSTOM_ID,
            label="Baka",
            emoji=CIRNO_HELP,
        )
        response_id = await ctx.respond(embed=embed, component=row)
        await db.create(bot.db, int(response_id))


@loader.listener(hikari.InteractionCreateEvent)
async def on_interaction(event: hikari.InteractionCreateEvent) -> None:
    """Persistent baka button — one press = one count."""
    interaction = event.interaction
    if not isinstance(interaction, hikari.ComponentInteraction):
        return
    if interaction.custom_id != CUSTOM_ID:
        return
    if interaction.message is None:
        return
    await _handle_baka(cast(CazzuBot, event.app), interaction)


async def _handle_baka(bot: CazzuBot, interaction: Any) -> None:
    """One baka press: bump the count, record the baka, update the embed."""
    mid = interaction.message.id

    # atomic increment — no lost updates under concurrent presses
    count_new = await db.bump_count(bot.db, mid)
    if count_new is None:
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            "This is not a baka counter anymore.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    user = interaction.user
    display_name = user.display_name
    await db.record_baka(
        bot.db,
        mid,
        user.id,
        display_name if isinstance(display_name, str) else user.username,
        pendulum.now("UTC").to_iso8601_string(),
    )

    names = await db.recent_bakas(bot.db, mid)

    embed = utils.prepare_embed(
        "Number of times people have touched the baka button",
        f"> {count_new}",
    )
    embed.set_thumbnail(BAKAPPLE)
    if names:
        embed.set_footer(
            text=f"{', '.join(names)} had recently done a baka!",
            icon=POGFROG,
        )
    else:
        embed.set_footer(text=NO_BAKAS_TEXT, icon=FROG)

    await interaction.create_initial_response(
        hikari.ResponseType.MESSAGE_UPDATE, embed=embed
    )

    await _schedule_expiry(bot, mid, interaction.channel_id)


async def _schedule_expiry(bot: CazzuBot, mid: int, cid: int) -> None:
    """Reset the 2h footer timer, replacing any pending wipe."""
    for task in await bot.scheduler.get("counter", {"mid": mid}):
        await bot.scheduler.drop(task.id)
    await bot.scheduler.add(
        "counter",
        pendulum.now("UTC").add(hours=2),
        {"mid": mid, "cid": cid},
    )


async def on_counter_expire(
    bot: CazzuBot, payload: dict[str, Any]
) -> None:
    """Scheduler handler for tag ``counter`` — reset the embed footer."""
    cid, mid = payload["cid"], payload["mid"]
    # clear the recent-baka list even if the message is already gone
    await db.clear_bakas(bot.db, mid)

    channel = bot.cache.get_guild_channel(cid)
    if channel is None:
        return
    try:
        msg = await bot.rest.fetch_message(cid, mid)
    except hikari.NotFoundError:
        return

    embed = msg.embeds[-1]
    embed.set_footer(text=NO_BAKAS_TEXT, icon=FROG)
    embed.set_thumbnail(BORED)
    await bot.rest.edit_message(cid, mid, embed=embed)


loader.command(counter)
