"""Frogs extension + factory tests — spawn math, register, consume, capture."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pendulum
import pytest

from cazzubot import utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db
from plugins.frogs import factory
from plugins.frogs.cog import Consume, Profile, Register
from tests.fakes import (
    invoke_command,
    FakeChannel,
    FakeContext,
    FakeInteraction,
    FakeMember,
    FakeMenuContext,
)

_UID = 424242


def _menu_button(menu: object, index: int = 0) -> Any:
    """The menu's button at ``index`` (callback drives the menu)."""
    return cast(list[Any], menu._rows[0])[index]  # pyright: ignore[reportPrivateUsage]


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
    await invoke_command(Profile(), ctx, member=author)
    assert (
        ctx.sent[-1].content
        == "No one has yet captured frogs in this server!"
    )


async def test_frog_register_upserts_spawn(
    bot: CazzuBot,
    ctx: FakeContext,
    channel: FakeChannel,
) -> None:
    await invoke_command(
        Register(),
        ctx,
        interval="2m",
        persist="30s",
        fuzzy=0.5,
        channel=channel,
    )
    spawns = await frog_db.get_spawns(bot.db)
    assert len(spawns) == 1
    assert spawns[0].interval == 120 and spawns[0].fuzzy == 0.5
    assert ctx.sent[-1].content == "✓ Spawn channel registered"


async def test_frog_register_rejects_short_interval(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(UserInputError):
        await invoke_command(Register(), ctx, interval="30s")


async def test_frog_register_rejects_bad_fuzzy(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(UserInputError):
        await invoke_command(Register(), ctx, interval="2m", fuzzy=2.0)


# -- consume -----------------------------------------------------------------


async def test_frog_consume_full_flow(
    bot: CazzuBot,
    ctx: FakeContext,
    author: FakeMember,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await frog_db.modify_frog(bot.db, _UID, modify=3)

    async def _fake_attach(
        menu: utils.ConfirmMenu, _client: object, **_: object
    ) -> None:
        # real attach waits on the menu's stop event; simulate a click-driven
        # termination by polling the value the callback sets.
        while menu.value is None:
            await asyncio.sleep(0.01)

    monkeypatch.setattr(utils.ConfirmMenu, "attach", _fake_attach)

    task = asyncio.create_task(invoke_command(Consume(), ctx, amount=2))
    await asyncio.sleep(0.05)  # let it reach menu.attach
    menu = ctx.sent[0].component
    assert isinstance(menu, utils.ConfirmMenu)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=author))
    await _menu_button(menu).callback(mctx)
    await task

    assert await frog_db.get_frogs(bot.db, _UID) == 1
    now = pendulum.now("UTC")
    assert (
        await exp_db.seasonal_exp(
            bot.db, _UID, now.year, (now.month - 1) // 3
        )
        == 20
    )  # 10 exp/frog * 2
    assert ctx.edits[-1]["embed"].title == "Frog(s) have been consumed!"


async def test_frog_consume_rejects_insufficient(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    await frog_db.modify_frog(bot.db, _UID, modify=1)
    with pytest.raises(UserInputError):
        await invoke_command(Consume(), ctx, amount=5)


async def test_frog_consume_rejects_zero(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    with pytest.raises(UserInputError):
        await invoke_command(Consume(), ctx, amount=0)


# -- capture menu -----------------------------------------------------------


async def test_frog_catch_captures_once(
    bot: CazzuBot, author: FakeMember
) -> None:
    await frog_db.set_message(bot.settings, {"content": "caught {name}"})
    menu = factory.FrogCatchMenu(bot)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=author))

    await _menu_button(menu).callback(mctx)

    assert menu.captured is True
    assert mctx.deferred is True
    assert mctx.stopped is True
    assert await frog_db.get_frogs(bot.db, _UID) == 1
    assert mctx.sent[0].content == "caught cirno"

    # second click is denied
    await _menu_button(menu).callback(mctx)
    assert mctx.sent[-1].content == "This frog was already caught."
    assert mctx.sent[-1].ephemeral is True


async def test_on_frog_due_reschedules_and_despawns(
    seeded_bot: CazzuBot, channel: FakeChannel
) -> None:
    await frog_db.set_enabled(seeded_bot.settings, True)
    payload = {
        "cid": channel.id,
        "interval": 120,
        "persist": 1,
        "fuzzy": 0.5,
    }

    await factory.on_frog_due(seeded_bot, payload)

    # next spawn was pre-rolled before this one spawned
    assert len(await seeded_bot.scheduler.get("frog")) == 1
    # frog message sent, then removed when bored
    assert len(channel.sent) == 1
    assert channel.sent[0]["content"] == factory.FROG_EMOJI
    assert seeded_bot.rest.deleted == [(channel.id, 1)]
