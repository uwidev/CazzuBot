"""Counter plugin tests — baka button, expiry handler, view re-attachment."""

from __future__ import annotations

import pytest

from cazzubot import utils
from cazzubot.bot import CazzuBot
from plugins.counter import (
    CounterCog,
    CounterPlugin,
    CounterView,
    NO_BAKAS_TEXT,
    on_counter_expire,
)
from tests.fakes import (
    FakeChannel,
    FakeContext,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    FakeMessage,
    first_button_custom_id,
    seed_guild,
)

_MID = 555


def _view(bot: CazzuBot) -> CounterView:
    return CounterView(bot)


async def test_counter_create_makes_message_and_row(
    bot: CazzuBot, ctx: FakeContext
) -> None:
    cog = bot.get_cog(CounterCog.__cog_name__)
    assert isinstance(cog, CounterCog)
    await cog.counter_create(ctx)
    assert ctx.sent[0].embed is not None
    row = await bot.db.fetchone("SELECT count FROM counter WHERE mid = 1")
    assert row is not None and row["count"] == 0


async def test_baka_press_increments_and_schedules(
    bot: CazzuBot, author: FakeMember, channel: FakeChannel
) -> None:
    message = FakeMessage(id=_MID, content="")
    await bot.db.execute(
        "INSERT OR IGNORE INTO counter (mid, count) VALUES (?, 0)", _MID
    )
    interaction = FakeInteraction(
        id=1, user=author, message=message, channel_id=channel.id
    )
    view = _view(bot)
    button = view.children[0]
    assert button.callback is not None

    await button.callback(interaction)

    row = await bot.db.fetchone(
        "SELECT count FROM counter WHERE mid = ?", _MID
    )
    assert row is not None and row["count"] == 1
    baka = await bot.db.fetchone(
        "SELECT name FROM counter_baka WHERE mid = ? AND uid = ?",
        _MID,
        author.id,
    )
    assert baka is not None and baka["name"] == "cirno"
    assert interaction.response.calls[0][0] == "edit_message"
    tasks = await bot.scheduler.get("counter")
    assert len(tasks) == 1 and tasks[0].payload["mid"] == _MID

    # second press replaces the pending expiry, not duplicates it
    await button.callback(interaction)
    assert len(await bot.scheduler.get("counter")) == 1


async def test_baka_press_unknown_counter(
    bot: CazzuBot, author: FakeMember
) -> None:
    message = FakeMessage(id=999, content="")
    interaction = FakeInteraction(id=1, user=author, message=message)
    view = _view(bot)
    button = view.children[0]
    assert button.callback is not None

    await button.callback(interaction)

    assert interaction.response.calls[0] == (
        "send_message",
        {
            "content": "This is not a baka counter anymore.",
            "ephemeral": True,
        },
    )


async def test_on_counter_expire_resets_footer(
    bot: CazzuBot, fake_guild: FakeGuild, channel: FakeChannel
) -> None:
    seed_guild(bot, fake_guild)
    embed = utils.prepare_embed("baka counter", "> 5")
    message = FakeMessage(id=_MID, content="", channel=channel)
    message.embeds = [embed]
    channel.messages.append(message)
    await bot.db.execute(
        "INSERT INTO counter_baka (mid, uid, name, updated_at)"
        + " VALUES (?, ?, ?, ?)",
        _MID,
        1,
        "cirno",
        "2026-01-01T00:00:00+00:00",
    )

    await on_counter_expire(bot, {"cid": channel.id, "mid": _MID})

    assert (
        await bot.db.fetchone(
            "SELECT 1 FROM counter_baka WHERE mid = ?", _MID
        )
        is None
    )
    assert message.edits[0]["embed"].footer.text == NO_BAKAS_TEXT


async def test_on_counter_expire_missing_message_noop(
    bot: CazzuBot, fake_guild: FakeGuild, channel: FakeChannel
) -> None:
    seed_guild(bot, fake_guild)
    await on_counter_expire(bot, {"cid": channel.id, "mid": 123})
    # no crash; baka rows are still cleared
    assert True


async def test_on_load_reattaches_counter_views(
    bot: CazzuBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    await bot.db.execute(
        "INSERT OR IGNORE INTO counter (mid, count) VALUES (?, 0)", _MID
    )
    calls: list[int] = []

    def spy(_view: CounterView, *, message_id: int) -> None:
        calls.append(message_id)

    monkeypatch.setattr(bot, "add_view", spy)

    await CounterPlugin().on_load(bot)

    assert calls == [_MID]
    assert first_button_custom_id(CounterView(bot)) == "counter:baka"
