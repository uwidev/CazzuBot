"""Poll plugin — app-command polls with a vote modal.

Single-guild port of v1's ``ext/poll.py`` + ``src/db/poll.py``. V1's half-
finished ``open`` command is replaced with a working flag toggle; voting stays
available whenever the poll message exists (as v1 effectively behaved). The
vote button view is persistent (``custom_id="poll:vote"``) and re-attached to
every existing poll message on boot via ``on_load`` + ``bot.add_view``.
"""

import logging
import random
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from cazzubot import Plugin, utils
from cazzubot.bot import CazzuBot
from cazzubot.db import Database
from typing_extensions import override

_log = logging.getLogger(__name__)

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS poll (
		id        INTEGER PRIMARY KEY AUTOINCREMENT,
		title     TEXT NOT NULL DEFAULT '',
		description TEXT NOT NULL DEFAULT '',
		max_vote  INTEGER NOT NULL DEFAULT 1,
		mid       INTEGER,
		open      INTEGER NOT NULL DEFAULT 0
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS poll_item (
		id  INTEGER PRIMARY KEY AUTOINCREMENT,
		pid INTEGER NOT NULL
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS poll_vote (
		pid   INTEGER NOT NULL,
		iid   INTEGER NOT NULL,
		uid   INTEGER NOT NULL,
		count INTEGER NOT NULL DEFAULT 1,
		PRIMARY KEY (pid, iid, uid)
	)
	""",
]

EMOJI_CLOSED = "https://files.catbox.moe/b67ajq.webp"
EMOJI_OPEN = "https://files.catbox.moe/xd4h7v.webp"


@dataclass(slots=True)
class Poll:
    """One ``poll`` row (``mid`` = the message id hosting the vote button)."""

    id: int
    title: str
    description: str
    max_vote: int
    mid: int | None
    open: int


@dataclass(slots=True)
class PollResult:
    """Aggregate vote counts per poll item (``iid`` → ``count``)."""

    iid: int
    count: int


@dataclass(slots=True)
class PollRow:
    """Narrow rows used for view re-attachment (``id`` + ``mid``)."""

    id: int
    mid: int | None


# -- db ---------------------------------------------------------------------


async def add_poll(
    db: Database, title: str, description: str, max_vote: int
) -> int | None:
    return await db.execute_lastrowid(
        """
		INSERT INTO poll (title, description, max_vote)
		VALUES (?, ?, ?)
		""",
        title,
        description,
        max_vote,
    )


async def get_poll(db: Database, pid: int) -> Poll | None:
    return await db.fetch_model(
        Poll, "SELECT * FROM poll WHERE id = ?", pid
    )


async def set_mid(db: Database, pid: int, mid: int) -> None:
    await db.execute("UPDATE poll SET mid = ? WHERE id = ?", mid, pid)


async def set_open(db: Database, pid: int, val: bool) -> None:
    await db.execute(
        "UPDATE poll SET open = ? WHERE id = ?", int(val), pid
    )


async def add_items_dummy(db: Database, pid: int, n: int) -> None:
    await db.executemany(
        "INSERT INTO poll_item (pid) VALUES (?)", [(pid,)] * n
    )


async def get_items(db: Database, pid: int) -> list[int]:
    """Poll item ids, ordered (used for vote validation ranges)."""
    rows = await db.fetchall(
        "SELECT id FROM poll_item WHERE pid = ? ORDER BY id", pid
    )
    return [int(r[0]) for r in rows]


async def add_votes(
    db: Database, pid: int, iids: list[int], uid: int
) -> None:
    await db.executemany(
        """
		INSERT INTO poll_vote (pid, iid, uid) VALUES (?, ?, ?)
		ON CONFLICT (pid, iid, uid) DO UPDATE SET
			count = poll_vote.count + 1
		""",
        [(pid, iid, uid) for iid in iids],
    )


async def drop_user_on_poll(db: Database, pid: int, uid: int) -> None:
    await db.execute(
        "DELETE FROM poll_vote WHERE pid = ? AND uid = ?", pid, uid
    )


async def get_results(db: Database, pid: int) -> list[PollResult]:
    return await db.fetch_models(
        PollResult,
        """
		SELECT vote.iid, SUM(vote.count) AS count
		FROM poll_vote AS vote
		WHERE vote.pid = ?
		GROUP BY vote.iid
		ORDER BY count DESC
		""",
        pid,
    )


# -- cog --------------------------------------------------------------------


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
        pid = await add_poll(self.bot.db, title, desc or "", max_vote)
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
        await add_items_dummy(self.bot.db, pid, n)
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
        poll = await get_poll(self.bot.db, poll_id)
        if not poll:
            await interaction.response.send_message(
                f"❌ Poll ID#{poll_id} does not exist!", ephemeral=True
            )
            return

        items = await get_items(self.bot.db, poll_id)
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
        await set_mid(self.bot.db, poll_id, msg.id)

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
        await set_open(self.bot.db, poll_id, open)
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
        votes = await get_results(self.bot.db, poll_id)
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
        poll = await get_poll(self.bot.db, self.poll_id)
        items = await get_items(self.bot.db, self.poll_id)
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
        poll: Poll,
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
            votes = self.parse_votes(self.vote_input.value)
            errors = self.validate_votes(votes)
            if errors:
                await interaction.response.send_message(
                    "❌ Invalid vote\n" + "\n".join(errors),
                    ephemeral=True,
                )
                return

            pid = self.poll.id
            uid = interaction.user.id
            await drop_user_on_poll(self.bot.db, pid, uid)
            await add_votes(self.bot.db, pid, votes, uid)
            await interaction.response.send_message(
                f"Your vote(s) of {votes} have been recorded.",
                ephemeral=True,
            )
        except (TypeError, ValueError) as err:
            await interaction.response.send_message(
                f"❌ Format error: {err}", ephemeral=True
            )

    def parse_votes(self, raw_input: str) -> list[int]:
        votes = [v.strip() for v in raw_input.split(",") if v]
        not_numbers = [
            v
            for v in votes
            if not (v.isdigit() or (v[0] == "-" and v[1:].isdigit()))
        ]
        if not_numbers:
            raise TypeError(f"Input is not a digit: {not_numbers}")
        if not votes:
            raise ValueError("No votes entered")
        return [int(v) for v in votes]

    def validate_votes(self, votes: list[int]) -> list[str]:
        errors: list[str] = []
        out_of_range = [
            v for v in votes if v not in range(1, self.upper + 1)
        ]
        if out_of_range:
            errors.append(
                f"Numbers out of range (1-{self.upper}): {out_of_range}"
            )
        if len(votes) > self.max_vote:
            errors.append(
                f"Too many votes (max {self.max_vote}): got {len(votes)}"
            )
        return errors


class PollPlugin(Plugin):
    name = "poll"
    schema = SCHEMA
    cogs = [PollCog]

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Re-attach the vote button to every existing poll message."""
        rows = await bot.db.fetch_models(
            PollRow, "SELECT id, mid FROM poll WHERE mid IS NOT NULL"
        )
        for row in rows:
            assert row.mid is not None  # WHERE mid IS NOT NULL
            bot.add_view(PollView(bot, row.id), message_id=row.mid)


plugin = PollPlugin()
