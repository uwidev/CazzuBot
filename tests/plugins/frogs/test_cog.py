"""Frogs cog + factory tests — spawn math, register, consume, capture view."""

from __future__ import annotations

import asyncio

import pendulum
import pytest
from discord.ext import commands

from cazzubot import utils
from cazzubot.bot import CazzuBot
from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db
from plugins.frogs import factory
from plugins.frogs.cog import FrogsCog
from tests.fakes import (
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    seed_guild,
)

_UID = 424242


def _cog(bot: CazzuBot) -> FrogsCog:
    cog = bot.get_cog(FrogsCog.__cog_name__)
    assert isinstance(cog, FrogsCog)
    return cog


# -- spawn math (pure) ------------------------------------------------------


def test_roll_future_frog_within_bounds() -> None:
    now = pendulum.now("UTC")
    for _ in range(50):
        dt = factory.roll_future_frog(now, 300, 0.5)
        delta = (dt - now).in_seconds()
        assert 150 <= delta <= 450  # 300s ± 50%


# -- profile / register -----------------------------------------------------


async def test_frog_profile_no_captures_yet(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await _cog(bot).frog(ctx, member=author)
    assert (
        ctx.sent[-1].content
        == "No one has yet captured frogs in this server!"
    )


async def test_frog_register_upserts_spawn(
    bot: CazzuBot,
    ctx: FakeContext,
    channel: FakeChannel,
) -> None:
    await _cog(bot).frog_register(
        ctx, "2m", persist="30s", fuzzy=0.5, channel=channel
    )
    spawns = await frog_db.get_spawns(bot.db)
    assert len(spawns) == 1
    assert spawns[0].interval == 120 and spawns[0].fuzzy == 0.5
    assert ctx.sent[-1].content == "✓ Spawn channel registered"


async def test_frog_register_rejects_short_interval(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(commands.BadArgument):
        await _cog(bot).frog_register(ctx, "30s")


async def test_frog_register_rejects_bad_fuzzy(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(commands.BadArgument):
        await _cog(bot).frog_register(ctx, "2m", fuzzy=2.0)


# -- consume -----------------------------------------------------------------


async def test_frog_consume_full_flow(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await frog_db.modify_frog(bot.db, _UID, modify=3)

    task = asyncio.create_task(_cog(bot).frog_consume(ctx, amount=2))
    await asyncio.sleep(0.05)  # let it reach view.wait()
    view = ctx.sent[0].view
    assert isinstance(view, utils.ConfirmView)
    interaction = FakeInteraction(id=1, user=author)
    yes = view.children[0]
    assert yes.callback is not None
    await yes.callback(interaction)
    await task

    assert await frog_db.get_frogs(bot.db, _UID) == 1
    now = pendulum.now("UTC")
    assert (
        await exp_db.seasonal_exp(
            bot.db, _UID, now.year, (now.month - 1) // 3
        )
        == 20
    )  # 10 exp/frog * 2
    assert ctx.returned[0].edits[0]["embed"].title == (
        "Frog(s) have been consumed!"
    )


async def test_frog_consume_rejects_insufficient(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await frog_db.modify_frog(bot.db, _UID, modify=1)
    with pytest.raises(commands.BadArgument):
        await _cog(bot).frog_consume(ctx, amount=5)


async def test_frog_consume_rejects_zero(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(commands.BadArgument):
        await _cog(bot).frog_consume(ctx, amount=0)


# -- capture view -----------------------------------------------------------


async def test_frog_catch_captures_once(
    bot: CazzuBot, author: FakeMember
) -> None:
    await frog_db.set_message(bot.settings, {"content": "caught {name}"})
    view = factory.FrogCatchView(bot)
    interaction = FakeInteraction(id=1, user=author)
    button = view.children[0]
    assert button.callback is not None

    await button.callback(interaction)

    assert view.captured is True
    assert interaction.response.calls[0][0] == "defer"
    assert await frog_db.get_frogs(bot.db, _UID) == 1
    assert len(interaction.followup.sent) == 1
    assert interaction.followup.sent[0]["content"] == "caught cirno"

    # second click is denied
    await button.callback(interaction)
    assert interaction.response.calls[-1] == (
        "send_message",
        {
            "content": "This frog was already caught.",
            "ephemeral": True,
        },
    )


async def test_on_frog_due_reschedules_and_despawns(
    bot: CazzuBot, fake_guild: FakeGuild, channel: FakeChannel
) -> None:
    seed_guild(bot, fake_guild)
    await frog_db.set_enabled(bot.settings, True)
    payload = {
        "cid": channel.id,
        "interval": 120,
        "persist": 1,
        "fuzzy": 0.5,
    }

    await factory.on_frog_due(bot, payload)

    # next spawn was pre-rolled before this one spawned
    assert len(await bot.scheduler.get("frog")) == 1
    # frog message sent, then removed when bored
    assert len(channel.sent) == 1
    assert channel.messages[0].content == factory.FROG_EMOJI
    assert channel.messages[0].deleted is True
