"""Fun plugin — small community commands.

Combines v1's ``ext/member.py`` (ping/info/noot/hashiresoriyo), ``ext/echo.py``,
``ext/inktober.py`` (reaction + scrape) and ``ext/story.py`` (channel story
compilation). Each cog is separate but ships in one plugin.
"""

import asyncio
import logging
import re
from collections import defaultdict
from pathlib import Path

import discord
from discord.ext import commands

from cazzubot import Plugin
from cazzubot.window import window_success

_log = logging.getLogger(__name__)


class MemberCog(commands.Cog):
    """General commands anyone can use."""

    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.hybrid_command()
    async def hashiresoriyo(self, ctx: commands.Context) -> None:
        """Gives you a jolly Saber."""
        await ctx.send("https://www.youtube.com/watch?v=dQ_d_VKrFgM")

    @commands.hybrid_command()
    async def info(
        self, ctx: commands.Context, *, member: discord.Member = None
    ) -> None:
        """Basic user information."""
        member = member or ctx.author
        await ctx.send(
            f"{member} joined on {member.joined_at} and has "
            f"{len(member.roles)} roles"
        )

    @commands.hybrid_command()
    async def noot(self, ctx: commands.Context) -> None:
        """Noot noot!"""
        await ctx.send("NOOT NOOT")

    @commands.hybrid_command()
    async def ping(self, ctx: commands.Context) -> None:
        """Ping the bot."""
        await ctx.send(
            f":ping_pong: Pong! {self.bot.latency * 1000:.2f}ms"
        )


class EchoCog(commands.Cog):
    """Echo commands."""

    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.hybrid_command()
    async def echo(self, ctx: commands.Context, *, content: str) -> None:
        """Echo your text back."""
        await ctx.send(content)


class InktoberCog(commands.Cog):
    """Inktober submission reactions and scraping."""

    submission_keyword = re.compile(r"inktober\s+day\s+\d\d?")

    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """React to valid inktober submissions in the watching channel."""
        watching_cid = await self.bot.settings.get("inktober.cid")
        if message.channel.id != watching_cid:
            return
        if (
            self.submission_keyword.search(message.content.lower())
            and message.attachments
        ):
            await message.add_reaction("👍")

    @commands.hybrid_command()
    async def register_inktober(
        self, ctx: commands.Context, channel: discord.TextChannel = None
    ) -> None:
        """Set the channel to watch for inktober submissions."""
        channel = channel or ctx.channel
        await self.bot.settings.set("inktober.cid", channel.id)
        await window_success(
            ctx, f"Inktober channel set to {channel.mention}"
        )

    @commands.hybrid_command()
    async def scrape_inktober(
        self, ctx: commands.Context, ch: discord.TextChannel = None
    ) -> None:
        """Download inktober submissions from a channel into downloads/."""
        ch = ch or ctx.channel
        day = None
        saved = 0
        async with ch.typing():
            async for message in ch.history(limit=None):
                if not message.attachments:
                    continue
                match = self.submission_keyword.search(
                    message.content.lower()
                )
                if not match:
                    continue
                day = re.search(r"\d+", match.group()).group()
                out = Path(f"downloads/{message.author.id}/{day}")
                out.mkdir(parents=True, exist_ok=True)
                for attachment in message.attachments:
                    await attachment.save(out / attachment.filename)
                    saved += 1
        await ctx.send(f"Saved {saved} submissions to downloads/.")


class StoryCog(commands.Cog):
    """Channel story compilation (v1 ext/story.py)."""

    def __init__(self, bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        return ctx.author.id == self.bot.owner_id

    @commands.hybrid_group()
    async def story(self, ctx: commands.Context) -> None:
        """Compile and write channel stories."""

    @story.command(name="compile")
    async def story_compile(self, ctx: commands.Context) -> None:
        """Save all messages in this channel to a .txt file with stats."""
        channel = ctx.channel
        # respond immediately with a status; the scan may exceed 3s, so the
        # result is delivered as an edit — never a bare defer
        status = None
        if ctx.interaction is not None:
            status = await ctx.send("Compiling channel history...")
        contributions = 0
        contributors: defaultdict[str, int] = defaultdict(int)

        async with channel.typing():
            Path("story").mkdir(exist_ok=True)
            with open(
                f"story/{channel.name}.txt", mode="w", encoding="utf-8"
            ) as file:
                async for message in channel.history(
                    limit=None,
                    before=ctx.message
                    if ctx.message is not None
                    else None,
                    oldest_first=True,
                ):
                    contributors[message.author.name] += 1
                    file.write(f"{message.content} ")
                    contributions += 1

            with open(
                f"story/{channel.name}-contributors.txt",
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
                        file.write(
                            f"**{name}: {count} ({percent:.2%})**\n"
                        )
                    else:
                        file.write(f"{name}: {count} ({percent:.2%})\n")

        if ctx.interaction is not None:
            await status.edit(
                content=f"Compiled {contributions} contributions to "
                f"story/{channel.name}.txt"
            )
        elif ctx.message is not None:
            await ctx.message.delete()

    @story.command(name="write")
    async def story_write(
        self, ctx: commands.Context, file_name: str
    ) -> None:
        """Write out a compiled story from story/."""
        await ctx.send(f"```fix\n>>> {file_name} <<<```")
        for suffix in ("", "-contributors"):
            path = Path(f"story/{file_name}{suffix}.txt")
            if not path.exists():
                continue
            chunk = ""
            with path.open(encoding="utf-8") as file:
                while True:
                    chunk = file.read(1900)
                    if not chunk:
                        break
                    await ctx.send(chunk)
                    await asyncio.sleep(2)
        if ctx.interaction is None and ctx.message is not None:
            await ctx.message.delete()


class FunPlugin(Plugin):
    name = "fun"
    cogs = [MemberCog, EchoCog, InktoberCog, StoryCog]


plugin = FunPlugin()
