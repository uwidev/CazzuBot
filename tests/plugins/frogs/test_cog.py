"""Frogs extension + factory tests — spawn math, register, consume, capture."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import hikari
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
    FakeCache,
    FakeChannel,
    FakeContext,
    FakeInteraction,
    FakeMember,
    FakeMenuContext,
    FakeMessage,
    FakeRest,
    invoke_command,
    menu_button,
    rest_of,
)

_UID = 424242


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
    client = cast(Any, ctx.client)
    for _ in range(200):  # wait for attach — no fixed-sleep race
        if client._attached_menus:  # pyright: ignore[reportPrivateUsage]
            break
        await asyncio.sleep(0.01)
    menu = ctx.sent[0].components
    assert isinstance(menu, utils.ConfirmMenu)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=author))
    await menu_button(menu).callback(mctx)
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
    seeded_bot: CazzuBot, author: FakeMember
) -> None:
    await frog_db.set_message(
        seeded_bot.settings, {"content": "caught {name}"}
    )
    menu = factory.FrogCatchMenu(seeded_bot, 99)
    interaction = FakeInteraction(id=1, member=author, channel_id=99)
    mctx = FakeMenuContext(interaction)

    await menu_button(menu).callback(mctx)

    assert menu.captured is True
    assert mctx.stopped is True
    # the click is acked silently (DEFERRED_MESSAGE_UPDATE — no response
    # message, no "thinking" bubble); the capture is a standalone channel
    # message, not an interaction response (no reply styling)
    assert (
        interaction.initial_response_type
        == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    assert mctx.sent == []
    created = rest_of(seeded_bot).created
    assert len(created) == 1
    assert created[0].content == "caught cirno"
    assert created[0].channel_id == 99
    assert await frog_db.get_frogs(seeded_bot.db, _UID) == 1

    # second click is denied
    await menu_button(menu).callback(mctx)
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


async def test_on_frog_due_skips_other_guild_channel(
    seeded_bot: CazzuBot, fake_cache: FakeCache
) -> None:
    """A spawn armed for the OTHER guild's channel never fires (the dev
    bot's DB can hold production spawn rows)."""
    await frog_db.set_enabled(seeded_bot.settings, True)
    other = FakeChannel(id=777, name="other", guild_id=999)
    fake_cache.add_channel(other)
    payload = {
        "cid": other.id,
        "interval": 120,
        "persist": 1,
        "fuzzy": 0.5,
    }

    await factory.on_frog_due(seeded_bot, payload)

    # the schedule still re-armed, but nothing spawned into the other guild
    assert len(await seeded_bot.scheduler.get("frog")) == 1
    assert other.sent == []


async def test_on_frog_due_rolls_from_fire_instant(
    seeded_bot: CazzuBot,
    channel: FakeChannel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The next spawn is rolled from the fire instant, not the despawn.

    persist=600 would anchor the old design at now+600; the pure chaotic
    timeline rolls interval ± 50% from now, so the armed row lands far
    before the despawn window.
    """
    await frog_db.set_enabled(seeded_bot.settings, True)
    payload = {
        "cid": channel.id,
        "interval": 120,
        "persist": 600,
        "fuzzy": 0.5,
    }

    async def _no_spawn(
        _bot: CazzuBot, _persist: int, _ctx: Any = None, **_: Any
    ) -> bool:
        return False

    monkeypatch.setattr(factory, "spawn_and_wait", _no_spawn)

    before = pendulum.now("UTC")
    await factory.on_frog_due(seeded_bot, payload)
    rows = await seeded_bot.scheduler.get("frog")
    assert len(rows) == 1
    run_at = pendulum.parse(rows[0].run_at)
    assert isinstance(run_at, pendulum.DateTime)
    # interval ± 50% from the fire instant — the upper bound is what
    # rejects the old despawn-anchored design (it would arm ≥ now+660)
    assert before.add(seconds=60) <= run_at
    assert run_at <= pendulum.now("UTC").add(seconds=180)


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


@pytest.mark.parametrize(
    ("with_message", "with_button"),
    [
        pytest.param(True, True, id="dangling-frog-deleted"),
        pytest.param(False, False, id="already-removed-silent"),
        pytest.param(True, False, id="repurposed-kept"),
    ],
)
async def test_cleanup_dangling_frogs(
    seeded_bot: CazzuBot,
    channel: FakeChannel,
    fake_rest: FakeRest,
    with_message: bool,
    with_button: bool,
) -> None:
    """Boot sweep: tracked frog messages are deleted, kept, or dropped."""
    mid = 7
    await frog_db.add_frog_message(seeded_bot.db, channel.id, mid)
    if with_message:
        fake_rest.messages[(channel.id, mid)] = _frog_message(
            channel.id, mid, with_button=with_button
        )

    await factory.cleanup_dangling_frogs(seeded_bot)

    expected = [(channel.id, mid)] if with_message and with_button else []
    assert rest_of(seeded_bot).deleted == expected
    assert await frog_db.get_frog_messages(seeded_bot.db) == []
