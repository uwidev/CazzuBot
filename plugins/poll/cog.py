"""Poll plugin extension — poll management commands, vote button, vote modal.

Single-guild port of v1's ``ext/poll.py``. Voting stays available whenever
the poll message exists. The vote button is a plain component whose custom id
carries the poll id (``poll:vote:<pid>``), handled by a component-interaction
listener so it survives restarts; the modal submission dispatches through
lightbulb's ``Modal.attach``.
"""

import asyncio
import random
from typing import Any, cast

import hikari
from typing_extensions import override
import lightbulb

from cazzubot import utils
from cazzubot.bot import CazzuBot
from lightbulb.components import modals
from lightbulb.prefab import checks as prefab_checks

from . import db
from .logic import parse_votes, validate_votes

loader = lightbulb.Loader()

EMOJI_CLOSED = "https://files.catbox.moe/b67ajq.webp"
EMOJI_OPEN = "https://files.catbox.moe/xd4h7v.webp"

_OWNER = prefab_checks.owner_only

poll = lightbulb.Group("poll", "Poll management.")
poll_item = poll.subgroup("item", "Poll item management.")


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


def build_send_payload(
    poll_row: db.Poll,
) -> tuple[hikari.Embed, hikari.impl.MessageActionRowBuilder]:
    """The embed + vote-button row for a poll's message.

    Shared by ``/poll send`` (which responds via the interaction) and the
    board weekly automation (which sends via ``bot.rest``).
    """
    embed = utils.prepare_embed(poll_row.title, poll_row.description)
    embed.set_footer(
        text=f"Poll ID#{poll_row.id}",
        icon=EMOJI_OPEN if poll_row.open else EMOJI_CLOSED,
    )
    row = hikari.impl.MessageActionRowBuilder().add_interactive_button(
        hikari.ButtonStyle.PRIMARY,
        f"poll:vote:{poll_row.id}",
        label="Vote",
        emoji="📥",
    )
    return embed, row


async def set_poll_open(
    bot: CazzuBot, pid: int, *, open: bool
) -> str | None:
    """Set the open flag and sync the vote button on the poll's message.

    Closing removes the button (and the vote flow refuses closed polls);
    opening re-adds it. Returns an error message when the poll doesn't
    exist. A missing message (deleted or pre-cid migration) only sets the
    flag — the DB is the source of truth.
    """
    poll_row = await db.get_poll(bot.db, pid)
    if poll_row is None:
        return f"Poll ID#{pid} does not exist!"
    await db.set_open(bot.db, pid, open)
    if poll_row.mid is not None and poll_row.cid is not None:
        refreshed = await db.get_poll(bot.db, pid)
        if refreshed is not None:
            embed, row = build_send_payload(refreshed)
            try:
                await bot.rest.edit_message(
                    poll_row.cid,
                    poll_row.mid,
                    embed=embed,
                    component=row if open else None,
                )
            except hikari.NotFoundError:
                # the poll message is gone — the flag is the source of truth
                pass
    return None


@poll.register
class Register(
    lightbulb.SlashCommand,
    name="register",
    description="Register a poll and get its ID.",
    hooks=[_OWNER],
):
    title = lightbulb.string("title", "The poll title")
    desc = lightbulb.string("desc", "The poll description", default=None)
    max_vote = lightbulb.integer(
        "max_vote", "Default total votes a user can submit", default=1
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        pid = await db.add_poll(
            bot.db, self.title, self.desc or "", self.max_vote
        )
        await ctx.respond(
            f"Your poll has been registered!\nReference it with ID#{pid}",
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@poll_item.register
class AutoPopulate(
    lightbulb.SlashCommand,
    name="auto_populate",
    description="Generate N empty items to vote on.",
    hooks=[_OWNER],
):
    pid = lightbulb.integer("pid", "Poll to generate items on")
    n = lightbulb.integer(
        "n", "Generate N items", min_value=1, max_value=50
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        if not 1 <= self.n <= 50:
            await ctx.respond(
                "n must be between 1 and 50.",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return
        await db.add_items_dummy(bot.db, self.pid, self.n)
        await ctx.respond(
            "👍 Items have been added.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@poll.register
class Send(
    lightbulb.SlashCommand,
    name="send",
    description="Send the message containing the poll and its vote button.",
    hooks=[_OWNER],
):
    poll_id = lightbulb.integer("poll_id", "ID associated with the poll")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Send the poll message with its vote button."""
        bot = _bot(ctx)
        poll_row = await db.get_poll(bot.db, self.poll_id)
        if not poll_row:
            await ctx.respond(
                f"❌ Poll ID#{self.poll_id} does not exist!",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        items = await db.get_items(bot.db, self.poll_id)
        if not items:
            await ctx.respond(
                "❌ Poll has 0 items to vote on!",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        embed, row = build_send_payload(poll_row)
        response_id = await ctx.respond(embed=embed, component=row)
        # respond() returns lightbulb's initial-response sentinel, not the
        # message id — fetch the real message id for the poll row
        message = await ctx.fetch_response(response_id)
        await db.set_mid(
            bot.db, self.poll_id, message.id, ctx.channel_id
        )


@poll.register
class Open(
    lightbulb.SlashCommand,
    name="open",
    description="Open or close voting on a poll (syncs its vote button).",
    hooks=[_OWNER],
):
    poll_id = lightbulb.integer("poll_id", "Poll ID to toggle")
    open = lightbulb.boolean(
        "open", "Open (default) or close", default=True
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        err = await set_poll_open(bot, self.poll_id, open=self.open)
        if err:
            await ctx.respond(err, flags=hikari.MessageFlag.EPHEMERAL)
            return
        await ctx.respond(
            f"Voting on poll ID#{self.poll_id} is now "
            + f"{'**open**' if self.open else '**closed**'}.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@poll.register
class Close(
    lightbulb.SlashCommand,
    name="close",
    description="Close voting on a poll and remove its vote button.",
    hooks=[_OWNER],
):
    poll_id = lightbulb.integer("poll_id", "Poll ID to close")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        err = await set_poll_open(bot, self.poll_id, open=False)
        if err:
            await ctx.respond(err, flags=hikari.MessageFlag.EPHEMERAL)
            return
        await ctx.respond(
            f"Voting on poll ID#{self.poll_id} is now **closed**.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )


@poll.register
class Stats(
    lightbulb.SlashCommand,
    name="stats",
    description="Show the current results from a poll.",
    hooks=[_OWNER],
):
    poll_id = lightbulb.integer("poll_id", "ID associated with the poll")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        votes = await db.get_results(bot.db, self.poll_id)
        if not votes:
            await ctx.respond(
                "No votes have been cast yet.",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        total = sum(v.count for v in votes)
        lines = "\n".join(
            f"{v.iid:<8}{v.count:>8}{v.count / total:>10.2%}"
            for v in votes[:10]
        )
        await ctx.respond(
            f"```{'Item':<8}{'Count':>8}{'Percent':>10}\n{lines}```"
        )


loader.command(poll)


# -- persistent vote button + modal ----------------------------------------


@loader.listener(hikari.InteractionCreateEvent)
async def on_interaction(event: hikari.InteractionCreateEvent) -> None:
    """Persistent vote button — open the vote modal for the poll."""
    interaction = event.interaction
    if not isinstance(interaction, hikari.ComponentInteraction):
        return
    prefix = "poll:vote:"
    if not interaction.custom_id.startswith(prefix):
        return
    poll_id = int(interaction.custom_id[len(prefix) :])
    await _handle_vote(cast(CazzuBot, event.app), interaction, poll_id)


async def _handle_vote(
    bot: CazzuBot, interaction: Any, poll_id: int
) -> None:
    """Open the vote modal; the attach wait runs in its own task so the
    event dispatch never blocks on a user's (up to 300s) modal session."""
    poll_row = await db.get_poll(bot.db, poll_id)
    items = await db.get_items(bot.db, poll_id)
    if not poll_row or not items:
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            "❌ This poll no longer exists.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return
    if not poll_row.open:
        await interaction.create_initial_response(
            hikari.ResponseType.MESSAGE_CREATE,
            "❌ Voting on this poll is closed.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )
        return

    modal = PollModal(bot, poll_row, items)
    custom_id = f"poll:submit:{poll_id}"
    await interaction.create_modal_response(
        "Vote on the poll",
        custom_id,
        # the modal is a sequence of row builders (no public build())
        components=cast(Any, modal),
    )

    async def _wait() -> None:
        try:
            await modal.attach(bot.lightbulb, custom_id, timeout=300)
        except asyncio.TimeoutError:
            pass

    asyncio.create_task(_wait())


class PollModal(modals.Modal):
    """Comma-separated item votes, validated against the poll's rules."""

    def __init__(
        self,
        bot: CazzuBot,
        poll_row: db.Poll,
        items: list[int],
    ) -> None:
        super().__init__()
        self.bot = bot
        self.poll = poll_row
        self.items = items
        self.max_vote = poll_row.max_vote
        self.upper = len(items)
        # Discord's modal rows accept ONLY text inputs (type 4) — the vote
        # range and max-vote rules live in the input's label and placeholder
        # (45/100 chars), with a short example.
        example = ", ".join(
            str(random.randint(1, self.upper))
            for _ in range(min(self.max_vote, self.upper, 3))
        )
        self.vote_input = self.add_paragraph_text_input(
            f"Vote (items 1-{self.upper}, max {self.max_vote})",
            placeholder=(
                f"Comma-separated item numbers, e.g. {example} — "
                f"same item may be voted multiple times"
            ),
        )

    @override
    async def on_submit(self, ctx: modals.ModalContext) -> None:
        raw = ctx.value_for(self.vote_input) or ""
        try:
            pid = self.poll.id
            # the poll may have closed while the user was typing
            poll_row = await db.get_poll(self.bot.db, pid)
            if poll_row is None or not poll_row.open:
                await ctx.respond(
                    "❌ Voting on this poll is closed.", ephemeral=True
                )
                return
            votes = parse_votes(raw)
            errors = validate_votes(
                votes, upper=self.upper, max_vote=self.max_vote
            )
            if errors:
                await ctx.respond(
                    "❌ Invalid vote\n" + "\n".join(errors),
                    ephemeral=True,
                )
                return

            uid = ctx.user.id
            await db.drop_user_on_poll(self.bot.db, pid, uid)
            await db.add_votes(self.bot.db, pid, votes, uid)
            await ctx.respond(
                f"Your vote(s) of {votes} have been recorded.",
                ephemeral=True,
            )
        except (TypeError, ValueError) as err:
            await ctx.respond(f"❌ Format error: {err}", ephemeral=True)
