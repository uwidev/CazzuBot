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
    FakeChannel,
    FakeContext,
    FakeInteraction,
    FakeMember,
    FakeMenuContext,
    FakeMessage,
    FakeRest,
    invoke_command,
    rest_of,
)

_UID = 424242


def _menu_button(menu: Any, index: int = 0) -> Any:
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
    menu = ctx.sent[0].components
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
    menu = factory.FrogCatchMenu(bot, 99)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=author))

    await _menu_button(menu).callback(mctx)

    assert menu.captured is True
    assert mctx.deferred is False  # no "app is thinking" defer
    assert mctx.stopped is True
    assert await frog_db.get_frogs(bot.db, _UID) == 1
    assert mctx.sent[0].content == "caught cirno"
    # the first response is the sentinel — the real message id is fetched
    # so the 7s auto-delete targets the actual capture message
    assert mctx.fetched == [utils.INITIAL_RESPONSE_IDENTIFIER]

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
    assert rest_of(seeded_bot).deleted == [(channel.id, 1)]


def _frog_message(
    cid: int, mid: int, *, with_button: bool = True
) -> FakeMessage:
    """A message whose components carry (or lack) the catch button."""
    from types import SimpleNamespace

    msg = FakeMessage(id=mid, channel_id=cid, guild_id=2)
    if with_button:
        button = SimpleNamespace(custom_id=f"frog:catch:{cid}")
        msg.components = [SimpleNamespace(components=[button])]
    return msg


async def test_frog_message_db_roundtrip(bot: CazzuBot) -> None:
    await frog_db.add_frog_message(bot.db, 99, 1)
    await frog_db.add_frog_message(bot.db, 99, 2)
    assert await frog_db.get_frog_messages(bot.db) == [(99, 1), (99, 2)]
    await frog_db.drop_frog_message(bot.db, 99, 1)
    assert await frog_db.get_frog_messages(bot.db) == [(99, 2)]


async def test_cleanup_deletes_dangling_frog(
    seeded_bot: CazzuBot, channel: FakeChannel, fake_rest: FakeRest
) -> None:
    """A tracked frog message from a previous process is deleted on boot."""
    mid = 7
    await frog_db.add_frog_message(seeded_bot.db, channel.id, mid)
    fake_rest.messages[(channel.id, mid)] = _frog_message(channel.id, mid)

    await factory.cleanup_dangling_frogs(seeded_bot)

    assert (channel.id, mid) in rest_of(seeded_bot).deleted
    assert await frog_db.get_frog_messages(seeded_bot.db) == []


async def test_cleanup_already_removed_is_silent(
    seeded_bot: CazzuBot, channel: FakeChannel
) -> None:
    """User/admin already deleted the frog — no error, row just dropped."""
    await frog_db.add_frog_message(seeded_bot.db, channel.id, 7)

    await factory.cleanup_dangling_frogs(seeded_bot)

    assert rest_of(seeded_bot).deleted == []
    assert await frog_db.get_frog_messages(seeded_bot.db) == []


async def test_cleanup_keeps_repurposed_message(
    seeded_bot: CazzuBot, channel: FakeChannel, fake_rest: FakeRest
) -> None:
    """A tracked message that lost its catch button is NOT deleted."""
    mid = 7
    await frog_db.add_frog_message(seeded_bot.db, channel.id, mid)
    fake_rest.messages[(channel.id, mid)] = _frog_message(
        channel.id, mid, with_button=False
    )

    await factory.cleanup_dangling_frogs(seeded_bot)

    assert rest_of(seeded_bot).deleted == []
    assert await frog_db.get_frog_messages(seeded_bot.db) == []
