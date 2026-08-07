"""Poll plugin — controller: app commands, vote button view, vote modal.

Single-guild port of v1's ``ext/poll.py``. V1's half-finished ``open`` command
is replaced with a working flag toggle; voting stays available whenever the
poll message exists (as v1 effectively behaved). The vote button view is
persistent (``custom_id="poll:vote"``) and re-attached to every existing poll
message on boot via ``on_load`` + ``bot.add_view``.
"""

import random
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from cazzubot import utils
from cazzubot.bot import CazzuBot
from typing_extensions import override

from . import db
from .logic import parse_votes, validate_votes

EMOJI_CLOSED = "https://files.catbox.moe/b67ajq.webp"
EMOJI_OPEN = "https://files.catbox.moe/xd4h7v.webp"


class PollCog(commands.Cog):
    """Poll management (app commands)."""

    def __init__(self, bot: CazzuBot) -> None:
        self.bot = bot

    @override
    async def cog_check(self, ctx: commands.Context[Any]) -> bool:
        return ctx.author.id == self.bot.owner_id

    poll_group = app_commands.Group(
        name="poll", description="Poll management"
    )

    @poll_group.command(name="register", description="Register a poll.")
    @app_commands.describe(
        max_vote="Default total votes a user can submit"
    )
    async def poll_register(
        self,
        interaction: discord.Interaction,
        title: str,
        desc: str | None = None,
        max_vote: int = 1,
    ) -> None:
        """Register a poll and get its ID."""
        pid = await db.add_poll(self.bot.db, title, desc or "", max_vote)
        await interaction.response.send_message(
            f"Your poll has been registered!\nReference it with ID#{pid}",
            ephemeral=True,
        )

    poll_item_group = app_commands.Group(
        parent=poll_group, name="item", description="Poll item management"
    )

    @poll_item_group.command(
        name="auto_populate",
        description="Generate N empty items to vote on.",
    )
    @app_commands.describe(
        pid="Poll to generate items on.", n="Generate N items."
    )
    async def poll_item_auto_populate(
        self, interaction: discord.Interaction, pid: int, n: int
    ) -> None:
        if not 1 <= n <= 50:
            await interaction.response.send_message(
                "n must be between 1 and 50.", ephemeral=True
            )
            return
        await db.add_items_dummy(self.bot.db, pid, n)
        await interaction.response.send_message(
            "👍 Items have been added.", ephemeral=True
        )

    @poll_group.command(
        name="send",
        description="Send the message containing the poll and its vote button.",
    )
    @app_commands.describe(poll_id="ID associated with the poll")
    async def poll_send(
        self, interaction: discord.Interaction, poll_id: int
    ) -> None:
        """Send the poll message with its vote button."""
        poll = await db.get_poll(self.bot.db, poll_id)
        if not poll:
            await interaction.response.send_message(
                f"❌ Poll ID#{poll_id} does not exist!", ephemeral=True
            )
            return

        items = await db.get_items(self.bot.db, poll_id)
        if not items:
            await interaction.response.send_message(
                "❌ Poll has 0 items to vote on!", ephemeral=True
            )
            return

        embed = utils.prepare_embed(poll.title, poll.description)
        embed.set_footer(
            text=f"Poll ID#{poll_id}",
            icon_url=EMOJI_OPEN if poll.open else EMOJI_CLOSED,
        )

        view = PollView(self.bot, poll_id)
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        view.message = msg
        await db.set_mid(self.bot.db, poll_id, msg.id)

    @poll_group.command(
        name="open",
        description="Open or close voting on a poll.",
    )
    @app_commands.describe(
        poll_id="Poll ID to toggle.", open="Open (default) or close."
    )
    async def poll_open(
        self,
        interaction: discord.Interaction,
        poll_id: int,
        open: bool = True,
    ) -> None:
        await db.set_open(self.bot.db, poll_id, open)
        await interaction.response.send_message(
            f"Voting on poll ID#{poll_id} is now "
            + f"{'**open**' if open else '**closed**'}.",
            ephemeral=True,
        )

    @poll_group.command(
        name="stats",
        description="Show the current results from a poll.",
    )
    @app_commands.describe(poll_id="ID associated with the poll")
    async def poll_stats(
        self, interaction: discord.Interaction, poll_id: int
    ) -> None:
        votes = await db.get_results(self.bot.db, poll_id)
        if not votes:
            await interaction.response.send_message(
                "No votes have been cast yet.", ephemeral=True
            )
            return

        total = sum(v.count for v in votes)
        lines = "\n".join(
            f"{v.iid:<8}{v.count:>8}{v.count / total:>10.2%}"
            for v in votes[:10]
        )
        await interaction.response.send_message(
            f"```{'Item':<8}{'Count':>8}{'Percent':>10}\n{lines}```"
        )


class PollView(discord.ui.View):
    """Persistent poll message view with the vote button."""

    def __init__(self, bot: CazzuBot, poll_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.poll_id = poll_id
        self.message: discord.InteractionMessage | None = None

    @discord.ui.button(
        label="Vote",
        style=discord.ButtonStyle.primary,
        emoji="📥",
        custom_id="poll:vote",
    )
    async def vote(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[Any],
    ) -> None:
        poll = await db.get_poll(self.bot.db, self.poll_id)
        items = await db.get_items(self.bot.db, self.poll_id)
        if not poll or not items:
            await interaction.response.send_message(
                "❌ This poll no longer exists.", ephemeral=True
            )
            return
        await interaction.response.send_modal(
            PollModal(self.bot, poll, items)
        )


class PollModal(discord.ui.Modal, title="Vote on the poll"):
    """Comma-separated item votes, validated against the poll's rules."""

    def __init__(
        self,
        bot: CazzuBot,
        poll: db.Poll,
        items: list[int],
    ) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.poll = poll
        self.items = items
        self.max_vote = poll.max_vote
        self.upper = len(items)

        self.rules: discord.ui.TextDisplay[Any] = discord.ui.TextDisplay(
            f"""
### Rules
- Max votes: {self.max_vote}
- Range: 1 to {self.upper}
- Can vote on same image multiple times
- Use comma-separated items to vote
			"""
        )
        self.add_item(self.rules)

        self.vote_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label="Vote",
            placeholder=(
                "Example: "
                + ", ".join(
                    str(random.randint(1, self.upper))
                    for _ in range(min(self.max_vote, self.upper))
                )
            ),
            style=discord.TextStyle.long,
        )
        self.add_item(self.vote_input)

    @override
    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            votes = parse_votes(self.vote_input.value)
            errors = validate_votes(
                votes, upper=self.upper, max_vote=self.max_vote
            )
            if errors:
                await interaction.response.send_message(
                    "❌ Invalid vote\n" + "\n".join(errors),
                    ephemeral=True,
                )
                return

            pid = self.poll.id
            uid = interaction.user.id
            await db.drop_user_on_poll(self.bot.db, pid, uid)
            await db.add_votes(self.bot.db, pid, votes, uid)
            await interaction.response.send_message(
                f"Your vote(s) of {votes} have been recorded.",
                ephemeral=True,
            )
        except (TypeError, ValueError) as err:
            await interaction.response.send_message(
                f"❌ Format error: {err}", ephemeral=True
            )
