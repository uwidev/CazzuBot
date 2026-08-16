"""Misc plugin extension — server utilities: banner, welcome screen, week.

``/misc banner`` sets the guild banner (16:9 crop, needs MANAGE_GUILD).
``/misc welcome`` edits the welcome screen's API-settable parts (enabled,
description, featured channel) — the welcome-screen *background image* is
client-side only and cannot be set via the API. ``/misc week`` reports the
current week of the year (Sunday- or Monday-start) and can place a
message link in its week — the link carries the message id, so the week
comes from snowflake decoding with no API calls.
"""

import hikari
import lightbulb
import pendulum

from cazzubot import utils
from cazzubot.window import window_error, window_success

from .logic import parse_message_link, prepare_banner, snowflake_time

loader = lightbulb.Loader()


async def _download(attachment: hikari.Attachment) -> bytes:
    """Fetch an attachment's bytes (module-level for test stubbing)."""
    return await hikari.files.URL(str(attachment.url)).read()


misc = lightbulb.Group(
    "misc",
    "Misc server utilities.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


@misc.register
class Banner(
    lightbulb.SlashCommand,
    name="banner",
    description="Set the server banner (16:9 crop of the image).",
    hooks=[utils.OWNER_ONLY],
):
    image = lightbulb.attachment(
        "image", "The image to use as the server banner", default=None
    )
    msg = lightbulb.string(
        "msg",
        "Link to a message whose first image becomes the banner",
        default=None,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = utils.bot_from(ctx)
        if self.msg is not None:
            link = parse_message_link(self.msg)
            if link is None:
                await window_error(
                    ctx,
                    "msg must be a Discord message link, e.g. "
                    "https://discord.com/channels/...",
                )
                return
            try:
                message = await bot.rest.fetch_message(
                    link.channel_id, link.message_id
                )
            except hikari.NotFoundError:
                await window_error(ctx, "That message no longer exists.")
                return
            except hikari.HikariError:
                await window_error(ctx, "Could not fetch that message.")
                return
            image = next(
                (
                    a
                    for a in message.attachments
                    if (a.media_type or "").startswith("image/")
                ),
                None,
            )
            if image is None:
                await window_error(
                    ctx, "That message has no image attachments."
                )
                return
            data = await _download(image)
        elif self.image is not None:
            data = await _download(self.image)
        else:
            await window_error(ctx, "Provide an image or a msg.")
            return
        try:
            banner = prepare_banner(data)
        except Exception:
            await window_error(ctx, "Could not read that image.")
            return
        try:
            await bot.rest.edit_guild(
                bot.config.guild_id,
                banner=hikari.Bytes(banner, "banner.jpg"),
            )
        except hikari.UnauthorizedError, hikari.ForbiddenError:
            await window_error(
                ctx, "Bot lacks MANAGE_GUILD — banner not changed."
            )
            return
        await window_success(ctx, "Server banner updated.")


@misc.register
class Welcome(
    lightbulb.SlashCommand,
    name="welcome",
    description="Set the welcome screen (community guilds).",
    hooks=[utils.OWNER_ONLY],
):
    enabled = lightbulb.boolean(
        "enabled", "Whether the welcome screen is shown"
    )
    description = lightbulb.string(
        "description", "Welcome text", default=None
    )
    channel = lightbulb.channel(
        "channel",
        "Channel to feature (default: keep current)",
        default=None,
        channel_types=[
            hikari.ChannelType.GUILD_TEXT,
            hikari.ChannelType.GUILD_NEWS,
        ],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = utils.bot_from(ctx)
        description: hikari.UndefinedOr[str] = hikari.UNDEFINED
        if self.description is not None:
            description = self.description
        channels: hikari.UndefinedNoneOr[list[hikari.WelcomeChannel]] = (
            hikari.UNDEFINED
        )
        if self.channel is not None:
            channels = [
                hikari.WelcomeChannel(
                    channel_id=self.channel.id, description=""
                )
            ]
        try:
            await bot.rest.edit_welcome_screen(
                bot.config.guild_id,
                enabled=self.enabled,
                description=description,
                channels=channels,
            )
        except hikari.NotFoundError:
            await window_error(
                ctx,
                "This server has no welcome screen set up yet — "
                + "create one in Server Settings first.",
            )
            return
        except hikari.UnauthorizedError, hikari.ForbiddenError:
            await window_error(
                ctx,
                "Bot lacks MANAGE_GUILD — welcome screen not changed.",
            )
            return
        except hikari.BadRequestError as err:
            await window_error(
                ctx, f"Welcome screen update rejected: {err}"
            )
            return
        await window_success(ctx, "Welcome screen updated.")


loader.command(misc)


@misc.register
class Week(
    lightbulb.SlashCommand,
    name="week",
    description="Show the current week of the year, or a message's week.",
    hooks=[utils.OWNER_ONLY],
):
    start = lightbulb.string(
        "start",
        "What day the week starts on (default: sunday)",
        default="sunday",
        choices=[
            lightbulb.Choice(name="sunday", value="sunday"),
            lightbulb.Choice(name="monday", value="monday"),
        ],
    )
    msg = lightbulb.string(
        "msg",
        "Link to a message (https://discord.com/channels/...)",
        default=None,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        # choices-validated by the option: always "sunday" or "monday"
        start = self.start
        if self.msg is not None:
            link = parse_message_link(self.msg)
            if link is None:
                await window_error(
                    ctx,
                    "msg must be a Discord message link, e.g. "
                    "https://discord.com/channels/...",
                )
                return
            when = snowflake_time(link.message_id)
            week, year = utils.week_number(when, start=start)
            line = (
                f"Message {link.message_id} (posted "
                f"{when.format('YYYY-MM-DD HH:mm')} UTC) — "
                f"https://discord.com/channels/{link.guild_id}/"
                f"{link.channel_id}/{link.message_id}"
            )
            line += f" is in {year}-W{week:02} (weeks start {start})."
            await window_success(ctx, line)
            return
        now = pendulum.now("UTC")
        week, year = utils.week_number(now, start=start)
        await window_success(
            ctx, f"It's {year}-W{week:02} right now (weeks start {start})."
        )
