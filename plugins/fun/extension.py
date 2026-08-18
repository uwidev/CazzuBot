"""Fun plugin extension — small community commands.

Combines v1's ``ext/member.py`` (ping/info/noot/hashiresoriyo), ``ext/echo.py``,
``ext/inktober.py`` (reaction + scrape) and ``ext/story.py`` (channel story
compilation).
"""

import asyncio
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import hikari
import lightbulb

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.listeners import guild_listener
from cazzubot.window import window_error, window_success

loader = lightbulb.Loader()


submission_keyword = re.compile(r"inktober\s+day\s+\d\d?")


# -- general commands -------------------------------------------------------


@loader.command()
class Hashiresoriyo(
    lightbulb.SlashCommand,
    name="hashiresoriyo",
    description="Gives you a jolly Saber.",
):
    """Give the invoker a jolly Saber."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Respond with the jolly Saber link."""
        await ctx.respond("https://www.youtube.com/watch?v=dQ_d_VKrFgM")


@loader.command()
class Info(
    lightbulb.SlashCommand,
    name="info",
    description="Basic user information.",
):
    """Show basic user information."""

    member = lightbulb.user("member", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Show the target's join date and role count."""
        target = self.member or ctx.member or ctx.user
        if not hasattr(target, "role_ids"):  # guild member only
            await ctx.respond("That user is not in this server.")
            return
        target = cast(hikari.Member, target)
        await ctx.respond(
            f"{target} joined on {target.joined_at} and has "
            + f"{len(target.role_ids)} roles"
        )


@loader.command()
class Noot(
    lightbulb.SlashCommand,
    name="noot",
    description="Noot noot!",
):
    """Noot noot!"""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Respond ``NOOT NOOT``."""
        await ctx.respond("NOOT NOOT")


@loader.command()
class Ping(
    lightbulb.SlashCommand,
    name="ping",
    description="Ping the bot.",
):
    """Ping the bot."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Respond with the current heartbeat latency."""
        bot = utils.bot_from(ctx)
        latency = max(bot.heartbeat_latency, 0.0)
        await ctx.respond(f":ping_pong: Pong! {latency * 1000:.2f}ms")


@loader.command()
class Echo(
    lightbulb.SlashCommand,
    name="echo",
    description="Echo your text back.",
):
    """Echo the invoker's text back."""

    content = lightbulb.string("content", "The text to echo")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Respond with the echoed content."""
        await ctx.respond(self.content)


# -- inktober ---------------------------------------------------------------


@guild_listener(loader, hikari.MessageCreateEvent)
async def on_message(event: hikari.MessageCreateEvent) -> None:
    """React to valid inktober submissions in the watching channel."""
    bot = cast(CazzuBot, event.app)
    watching_cid = await bot.settings.get("inktober.cid")
    message = event.message
    if message.channel_id != watching_cid:
        return
    if (
        submission_keyword.search((message.content or "").lower())
        and message.attachments
    ):
        await bot.rest.add_reaction(message.channel_id, message.id, "👍")


@loader.command()
class RegisterInktober(
    lightbulb.SlashCommand,
    name="register_inktober",
    description="Set the channel to watch for inktober submissions.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
    hooks=[utils.ADMIN_ONLY],
):
    """Set the channel to watch for inktober submissions."""

    channel = lightbulb.channel(
        "channel",
        "The channel to watch (default: this channel)",
        default=None,
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Persist the inktober watching channel."""
        bot = utils.bot_from(ctx)
        target_id = (
            self.channel.id if self.channel is not None else ctx.channel_id
        )
        await bot.settings.set("inktober.cid", target_id)
        await window_success(
            ctx, f"Inktober channel set to <#{target_id}>"
        )


@loader.command()
class ScrapeInktober(
    lightbulb.SlashCommand,
    name="scrape_inktober",
    description="Download inktober submissions from a channel into downloads/.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
    hooks=[utils.OWNER_ONLY],
):
    """Download inktober submissions into ``downloads/``."""

    channel = lightbulb.channel(
        "channel",
        "The channel to scrape (default: this channel)",
        default=None,
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Scrape and save matching inktober submissions."""
        bot = utils.bot_from(ctx)
        target_id = (
            self.channel.id if self.channel is not None else ctx.channel_id
        )
        saved = 0
        await ctx.respond("Scraping inktober submissions...")
        messages = cast(Any, bot.rest.fetch_messages(target_id))
        async for message in messages:
            if not message.attachments:
                continue
            match = submission_keyword.search(
                (message.content or "").lower()
            )
            if not match:
                continue
            day_match = re.search(r"\d+", match.group())
            if day_match is None:
                continue
            day = day_match.group()
            out = Path(f"downloads/{message.author.id}/{day}")
            out.mkdir(parents=True, exist_ok=True)
            for attachment in message.attachments:
                data = await hikari.files.URL(str(attachment.url)).read()
                out.joinpath(attachment.filename).write_bytes(data)
                saved += 1
        await ctx.respond(f"Saved {saved} submissions to downloads/.")


# -- story ------------------------------------------------------------------


story = lightbulb.Group(
    "story",
    "Compile and write channel stories.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


@story.register
class StoryCompile(
    lightbulb.SlashCommand,
    name="compile",
    description="Save all messages in this channel to a .txt file with stats.",
    hooks=[utils.OWNER_ONLY],
):
    """Save all messages in this channel to a .txt file with stats."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Save all messages in this channel to a .txt file with stats."""
        bot = utils.bot_from(ctx)
        channel = bot.cache.get_guild_channel(ctx.channel_id)
        if channel is None or not hasattr(channel, "name"):
            await ctx.respond("Stories need a text channel.")
            return
        channel_name = cast(Any, channel).name
        # respond immediately with a status; the scan may exceed 3s, so the
        # result is delivered as an edit
        response_id = await ctx.respond("Compiling channel history...")
        contributions = 0
        contributors: defaultdict[str, int] = defaultdict(int)

        Path("story").mkdir(exist_ok=True)
        with open(
            f"story/{channel_name}.txt", mode="w", encoding="utf-8"
        ) as file:
            messages = cast(Any, bot.rest.fetch_messages(ctx.channel_id))
            async for message in messages:
                contributors[message.author.display_name] += 1
                file.write(f"{message.content} ")
                contributions += 1

        with open(
            f"story/{channel_name}-contributors.txt",
            mode="w",
            encoding="utf-8",
        ) as file:
            file.write(
                f".\n.\n.\n__**Total contributions: {contributions}**__\n"
            )
            for i, (name, count) in enumerate(
                sorted(
                    contributors.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )
            ):
                percent = count / contributions
                if i < 5:
                    file.write(f"**{name}: {count} ({percent:.2%})**\n")
                else:
                    file.write(f"{name}: {count} ({percent:.2%})\n")

        await ctx.edit_response(
            response_id,
            content=f"Compiled {contributions} contributions to "
            + f"story/{channel_name}.txt",
        )


@story.register
class StoryWrite(
    lightbulb.SlashCommand,
    name="write",
    description="Write out a compiled story from story/.",
    hooks=[utils.OWNER_ONLY],
):
    """Write out a compiled story from ``story/``."""

    file_name = lightbulb.string("file_name", "The story file name")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Write out a compiled story from story/."""
        if "/" in self.file_name or "\\" in self.file_name:
            await window_error(
                ctx, "file_name must be a plain file name, not a path"
            )
            return
        await ctx.respond(f"```fix\n>>> {self.file_name} <<<```")
        for suffix in ("", "-contributors"):
            path = Path(f"story/{self.file_name}{suffix}.txt")
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as file:
                while True:
                    chunk = file.read(1900)
                    if not chunk:
                        break
                    await ctx.respond(chunk)
                    await asyncio.sleep(2)


loader.command(story)
