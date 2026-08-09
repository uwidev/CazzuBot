"""Fun plugin extension — small community commands.

Combines v1's ``ext/member.py`` (ping/info/noot/hashiresoriyo), ``ext/echo.py``,
``ext/inktober.py`` (reaction + scrape) and ``ext/story.py`` (channel story
compilation).
"""

import asyncio
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import hikari
import lightbulb

from cazzubot.bot import CazzuBot
from cazzubot.window import window_error, window_success
from lightbulb.prefab import checks as prefab_checks

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

_OWNER = prefab_checks.owner_only

submission_keyword = re.compile(r"inktober\s+day\s+\d\d?")


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


# -- general commands -------------------------------------------------------


@loader.command()
class Hashiresoriyo(
    lightbulb.SlashCommand,
    name="hashiresoriyo",
    description="Gives you a jolly Saber.",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond("https://www.youtube.com/watch?v=dQ_d_VKrFgM")


@loader.command()
class Info(
    lightbulb.SlashCommand,
    name="info",
    description="Basic user information.",
):
    member = lightbulb.user("member", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
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
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond("NOOT NOOT")


@loader.command()
class Ping(
    lightbulb.SlashCommand,
    name="ping",
    description="Ping the bot.",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        latency = max(bot.heartbeat_latency, 0.0)
        await ctx.respond(f":ping_pong: Pong! {latency * 1000:.2f}ms")


@loader.command()
class Echo(
    lightbulb.SlashCommand,
    name="echo",
    description="Echo your text back.",
):
    content = lightbulb.string("content", "The text to echo")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond(self.content)


# -- inktober ---------------------------------------------------------------


@loader.listener(hikari.MessageCreateEvent)
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
):
    channel = lightbulb.channel(
        "channel",
        "The channel to watch (default: this channel)",
        default=None,
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
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
    hooks=[_OWNER],
):
    channel = lightbulb.channel(
        "channel",
        "The channel to scrape (default: this channel)",
        default=None,
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        target_id = (
            self.channel.id if self.channel is not None else ctx.channel_id
        )
        day = None
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


story = lightbulb.Group("story", "Compile and write channel stories.")


@story.register
class StoryCompile(
    lightbulb.SlashCommand,
    name="compile",
    description="Save all messages in this channel to a .txt file with stats.",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Save all messages in this channel to a .txt file with stats."""
        bot = _bot(ctx)
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
    hooks=[_OWNER],
):
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
