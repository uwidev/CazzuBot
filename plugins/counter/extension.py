"""Counter plugin extension — baka button view, create/re-create, expiry.

Single-guild port of v1's ``ext/counter.py``. A registered counter message
carries a persistent button; each press appends one ``counter_event`` row,
the footer shows who "did a baka" recently (2h window), and a 2-hour expiry
task (tag ``counter``) resets the footer. The button is a plain component
with a fixed custom id handled by a component-interaction listener, so it
survives restarts without re-registration. ``/counter create`` gains an
optional ``counter_id`` to re-create a counter whose message was deleted —
the events (and the count) carry over.
"""

from typing import Any, cast

import hikari
import lightbulb
import pendulum

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.listeners import guild_listener
from cazzubot.errors import UserInputError

from . import db

loader = lightbulb.Loader()


FROG = "https://files.catbox.moe/qo7bkv.gif"
POGFROG = "https://files.catbox.moe/k5qvvd.gif"
BAKAPPLE = "https://files.catbox.moe/og9q1l.gif"
BORED = "https://files.catbox.moe/0ex005.gif"
CIRNO_HELP = "<:cirnoHelp:695126168227151954>"

NO_BAKAS_TEXT = "There are no bakas as of recently..."

CUSTOM_ID = "counter:baka"

RECENT_WINDOW_HOURS = 2


counter = lightbulb.Group(
    "counter",
    "Baka counter management.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


def _counter_embed(
    count: int, *, thumbnail: str, footer_text: str, footer_icon: str
) -> hikari.Embed:
    """The baka counter embed — shared by create and every press."""
    embed = utils.prepare_embed(
        "Number of times people have touched the baka button",
        f"> {count}",
    )
    embed.set_thumbnail(thumbnail)
    embed.set_footer(text=footer_text, icon=footer_icon)
    return embed


@counter.register
class Create(
    lightbulb.SlashCommand,
    name="create",
    description="Create the baka counter message in this channel.",
    hooks=[utils.ADMIN_ONLY],
):
    counter_id = lightbulb.integer(
        "counter_id",
        "Re-create a deleted counter by its id (keeps the count)",
        default=None,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = utils.bot_from(ctx)
        count = 0
        if self.counter_id is not None:
            if await db.by_id(bot.db, self.counter_id) is None:
                raise UserInputError(
                    f"counter #{self.counter_id} does not exist"
                )
            count = await db.count_by_id(bot.db, self.counter_id)

        embed = _counter_embed(
            count,
            thumbnail=BORED,
            footer_text=NO_BAKAS_TEXT,
            footer_icon=FROG,
        )
        row = hikari.impl.MessageActionRowBuilder().add_interactive_button(
            hikari.ButtonStyle.PRIMARY,
            CUSTOM_ID,
            label="Baka",
            # buttons need the emoji id, not the <:name:id> tag
            emoji=utils.button_emoji(CIRNO_HELP),
        )
        response_id = await ctx.respond(embed=embed, component=row)
        # respond() returns lightbulb's initial-response sentinel, not the
        # message id — fetch the real message so the baka button's
        # custom-id handler can find the counter row
        message = await ctx.fetch_response(response_id)
        if self.counter_id is not None:
            await db.reattach(bot.db, self.counter_id, message.id)
        else:
            await db.create(bot.db, message.id)


@guild_listener(loader, hikari.InteractionCreateEvent)
async def on_interaction(event: hikari.InteractionCreateEvent) -> None:
    """Persistent baka button — one press = one count."""
    interaction = event.interaction
    if not isinstance(interaction, hikari.ComponentInteraction):
        return
    if interaction.custom_id != CUSTOM_ID:
        return
    await _handle_baka(cast(CazzuBot, event.app), interaction)


async def _handle_baka(bot: CazzuBot, interaction: Any) -> None:
    """One baka press: append an event, show the count + recent bakas."""
    mid = interaction.message.id

    counter = await db.by_mid(bot.db, mid)
    if counter is None:
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            "This is not a baka counter anymore.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    user = interaction.user
    display_name = user.display_name
    now = pendulum.now("UTC")
    await db.record_event(
        bot.db,
        counter["id"],
        user.id,
        display_name if isinstance(display_name, str) else user.username,
        now.to_iso8601_string(),
    )

    count_new = await db.count_by_id(bot.db, counter["id"])
    names = await db.recent_names(
        bot.db,
        counter["id"],
        now.subtract(hours=RECENT_WINDOW_HOURS).to_iso8601_string(),
    )

    if names:
        embed = _counter_embed(
            count_new,
            thumbnail=BAKAPPLE,
            footer_text=f"{', '.join(names)} had recently done a baka!",
            footer_icon=POGFROG,
        )
    else:
        embed = _counter_embed(
            count_new,
            thumbnail=BAKAPPLE,
            footer_text=NO_BAKAS_TEXT,
            footer_icon=FROG,
        )

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
        pendulum.now("UTC").add(hours=RECENT_WINDOW_HOURS),
        {"mid": mid, "cid": cid},
    )


async def on_counter_expire(
    bot: CazzuBot, payload: dict[str, Any]
) -> None:
    """Scheduler handler for tag ``counter`` — reset the embed footer.

    Events are the history and are never deleted; only the message
    display resets back to the idle footer.
    """
    cid, mid = payload["cid"], payload["mid"]

    if not utils.channel_in_guild(bot, cid):
        # a row armed while the bot served the other guild — never touch
        # its message under this guild mode
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
