"""Frog spawn/catch through the offline driver (manual D4 scenario).

``frog spawn`` blocks on the catch menu like in production; the test
presses the catch button the way a user would and asserts the whole
capture pipeline (DB rows, silent click ack, capture as a standalone
channel message, frog message cleanup) plus the stale-button behavior
after the catch. The spawned frog is a rolled species, so the catch
button's custom_id carries it (``frog:catch:<cid>:<key>``).
"""

from __future__ import annotations

import asyncio

import hikari
import pendulum
import pytest

from core.bot import CazzuBot
from core.models import FrogItemKey
from core.statuses import STATUS_CONVERGE_TAG, Scope
from core.tips import TIP_SETS
from tests.driver import press_button, run_slash, wait_for_menu
from tests.fakes import InstantAsyncio, rest_of

from plugins.frogs.seams import FrogSeam

# the dev-guild classy role (FROG.md); tests run guild_kind=development
_CLASSY_ROLE_DEV = 1542294599358353430


def _catch_button(buttons: dict[str, str]) -> str:
    """The spawned frog's catch custom_id (species suffix rolled at spawn)."""
    matches = [
        cid for cid in buttons.values() if cid.startswith("frog:catch:99:")
    ]
    assert matches, f"no catch button for channel 99 in {buttons}"
    return matches[0]


async def test_frog_spawn_then_catch(full_bot: CazzuBot) -> None:
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "frog spawn",
            # five species roll by weight now — pin Basic so the rolled
            # species key (and the catch button) is deterministic
            options={"species": "basic"},
            user_id=1,
            username="owner",
            # the command blocks on the catch menu (30s attach window)
            timeout=40.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    catch_id = _catch_button(buttons)
    species_key = catch_id.rsplit(":", 1)[-1]

    press = await press_button(
        full_bot,
        custom_id=catch_id,
        message_id=555,
        user_id=424242,
    )
    spawn = await task

    assert press.exceptions == []
    assert spawn.exceptions == []
    # the click is acked silently — DEFERRED_MESSAGE_UPDATE (no response
    # message, no "thinking" bubble); the capture is a standalone channel
    # message, not an interaction response (no reply styling)
    assert (
        press.response_type == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    assert press.response_message_id is None
    assert spawn.followups == []
    # exactly one standalone channel message: the frog itself was spawned
    # via the slash interaction response (webhook-minted, not in `created`)
    created = rest_of(full_bot).created
    assert len(created) == 1
    assert created[0].channel_id == 99
    # the capture announcement is the hardcoded built-in embed — the
    # /frog set message template path is gone, so no template is involved
    assert created[0].embeds[0].title == "Congrats on your catch!"
    # the catcher's mention + ping live on the message content (Discord
    # does not resolve pings inside embeds) — and nothing else does; the
    # counts ride in the embed below
    assert created[0].content == "<@424242>"
    assert "None" not in created[0].content
    embed = created[0].embeds[0]
    assert embed.description is not None
    assert "+1 to froggies" in embed.description
    # the rolled-species catch states the caught item's old->new stack — a
    # first catch is `0` -> `1` in its fresh species stack — plus the
    # season's captures and the total froggies old->new
    assert "**Basic Frog**: `0` -> `1`" in embed.description
    assert "**Seasonal Captures**: `0` -> `1`" in embed.description
    assert "**Total Froggies**: `0` -> `1`" in embed.description
    # the thumbnail references the CATCH_BANNER media asset (unpublished
    # in offline boots → no thumbnail) + a cycling footer tip from the
    # shared frog set
    assert embed.thumbnail is None
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["frog"]
    # capture recorded: inventory row for the rolled species + capture
    # counter; the log row stores the species key
    row = await full_bot.db.fetchone(
        """
		SELECT qty FROM inventory
		WHERE uid = 424242 AND item = ?
		""",
        f"frog:{species_key}:normal",
    )
    assert row is not None and row["qty"] == 1
    assert (
        await full_bot.db.fetchval(
            "SELECT capture FROM member_frog WHERE uid = 424242"
        )
        == 1
    )
    assert (
        await full_bot.db.fetchval(
            "SELECT type FROM member_frog_log WHERE uid = 424242"
        )
        == species_key
    )
    # the frog message is deleted after the catch
    frog_mid = spawn.response_message_id
    assert frog_mid is not None
    assert (99, frog_mid) in rest_of(full_bot).deleted


async def test_catch_button_is_stale_after_capture(
    full_bot: CazzuBot,
) -> None:
    """A second press on the caught frog is silently ignored (menu gone)."""
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "frog spawn",
            options={"species": "basic"},
            user_id=1,
            username="owner",
            timeout=40.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    catch_id = _catch_button(buttons)
    first = await press_button(
        full_bot,
        custom_id=catch_id,
        message_id=555,
        user_id=424242,
    )
    await task
    assert (
        first.response_type == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )

    second = await press_button(
        full_bot,
        custom_id=catch_id,
        message_id=555,
        user_id=7,
    )
    # no menu matches any more: no response, no crash
    assert not second.responded
    assert second.exceptions == []


async def test_consume_pog_via_driver_publishes_reaction_seam(
    full_bot: CazzuBot,
) -> None:
    """/inventory consume of a Pog publishes the reaction seam (no exp)."""
    await full_bot.db.execute(
        """
		INSERT OR IGNORE INTO inventory (uid, item, qty)
		VALUES (424242, 'frog:pog:normal', 2)
		"""
    )
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "inventory consume",
            options={"slot": 1},
            user_id=424242,
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    press = await press_button(
        full_bot, custom_id=buttons["Yes"], message_id=555, user_id=424242
    )
    result = await task
    assert press.exceptions == [] and result.exceptions == []
    # exp is chatting-only: the consume path writes no exp row at all
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM member_exp_log WHERE uid = 424242"
        )
        == 0
    )
    contribs = await full_bot.statuses.list(
        Scope.member(424242), FrogSeam.FROG_REACTION
    )
    assert len(contribs) == 1
    assert contribs[0].source == "frog:blessing:pog"  # the status class
    assert contribs[0].payload == {"from": "frog:pog:normal"}


async def test_consume_classy_via_driver_grants_role(
    full_bot: CazzuBot,
) -> None:
    """Classy consume adds the dev-guild role through the converger."""
    await full_bot.db.execute(
        """
		INSERT OR IGNORE INTO inventory (uid, item, qty)
		VALUES (424242, 'frog:classy:normal', 1)
		"""
    )
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "inventory consume",
            options={"slot": 1},
            user_id=424242,
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    press = await press_button(
        full_bot, custom_id=buttons["Yes"], message_id=555, user_id=424242
    )
    result = await task
    assert press.exceptions == [] and result.exceptions == []
    member = await full_bot.rest.fetch_member(
        full_bot.config.guild_id, 424242
    )
    assert _CLASSY_ROLE_DEV in member.role_ids
    # expiry: prune the row via a read past the window (lazy data expiry),
    # then fire the converge job the way the scheduler would at expires_at
    await full_bot.statuses.list(
        Scope.member(424242),
        FrogSeam.CLASSY_ROLE,
        now=pendulum.now("UTC").add(hours=4),
    )
    payload = {
        "retry": True,
        "scope_kind": "member",
        "scope_id": 424242,
        "seam": FrogSeam.CLASSY_ROLE.key,
        "source": "frog:blessing:classy",
    }
    await full_bot.scheduler.handlers[STATUS_CONVERGE_TAG](
        full_bot, payload
    )
    member = await full_bot.rest.fetch_member(
        full_bot.config.guild_id, 424242
    )
    assert _CLASSY_ROLE_DEV not in member.role_ids


async def test_capture_cluster_bursts_basics_no_item(
    full_bot: CazzuBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catching a Cluster Frog bursts Basics; the catcher gets no item.

    The cluster frog spawns like any catchable frog, and the catch runs
    the whole pipeline: silent ack, ledger (log + counter), the burst
    announcement + child Basic frogs, the captured event — but no
    inventory grant (``frog:cluster:*`` does not exist).
    """
    from tests.fakes import FakeChannel

    from plugins.frogs.behaviors import ClusterBurst
    from plugins.frogs.species import by_key
    import plugins.frogs.behaviors as behaviors_mod

    # seed text channels around 99 (the driver's default channel)
    gid = full_bot.config.guild_id
    guild = rest_of(full_bot).guilds[gid]
    for cid_, pos in ((98, 1), (99, 2), (100, 3)):
        channel = FakeChannel(id=cid_, guild_id=gid)
        channel.position = pos
        guild.channels[cid_] = channel
    # the burst fires background tasks — capture them without blocking
    spawned: list[tuple[int, FrogItemKey | None]] = []

    async def recording_spawn(
        b,
        persist,
        cid: int | None = None,
        species_key: FrogItemKey | None = None,
    ) -> bool:
        spawned.append((cid or 0, species_key))
        return False

    cluster = by_key(FrogItemKey.CLUSTER)
    assert cluster is not None and isinstance(cluster.catch, ClusterBurst)
    original = cluster.catch.spawn_impl
    cluster.catch.spawn_impl = recording_spawn
    # the burst sleeps 0.75s between children (Discord rate-limit guard);
    # that timing isn't what this test asserts — stub the module binding,
    # never the global asyncio (the driver harness polls on it)
    monkeypatch.setattr(behaviors_mod, "asyncio", InstantAsyncio())
    try:
        task = asyncio.create_task(
            run_slash(
                full_bot,
                "frog spawn",
                options={"species": "cluster"},
                user_id=1,
                username="owner",
                timeout=10.0,
            )
        )
        buttons = await wait_for_menu(full_bot)
        catch_id = _catch_button(buttons)
        press = await press_button(
            full_bot,
            custom_id=catch_id,
            message_id=555,
            user_id=424242,
        )
        spawn = await task
    finally:
        cluster.catch.spawn_impl = original
    assert press.exceptions == [] and spawn.exceptions == []
    # the click is acked silently — DEFERRED_MESSAGE_UPDATE; the frog
    # message is deleted on the spot
    assert (
        press.response_type == hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    frog_mid = spawn.response_message_id
    assert frog_mid is not None
    assert (99, frog_mid) in rest_of(full_bot).deleted
    # the burst announcement is the one standalone channel message (the
    # frog itself was the slash response, webhook-minted)
    created = rest_of(full_bot).created
    assert len(created) == 1
    msg = created[0]
    assert msg.channel_id == 99
    embed = msg.embeds[0]
    assert embed.title == "Cluster Frog burst!"
    # the catcher's mention + ping live on the message content (Discord
    # does not resolve pings inside embeds), not in the embed
    assert "<@424242>" in msg.content
    # cluster frogs are never caught — the copy says the catch failed
    # and the frog burst instead; the burst outcome count is the "new
    # count" line, and the embed stays thumbnail-free
    assert "burst" in msg.content
    assert "Basic Frogs" in msg.content
    assert "caught a" not in msg.content
    assert "None" not in msg.content
    assert embed.thumbnail is None
    assert "<@424242>" not in (embed.description or "")
    assert "burst" in (embed.description or "")
    assert msg.create_kwargs is not None
    assert msg.create_kwargs["user_mentions"] == [424242]
    # children fired as Basic frogs into the zone
    for _ in range(100):
        if len(spawned) >= 4:
            break
        await asyncio.sleep(0.01)
    assert 4 <= len(spawned) <= 6
    assert all(key == FrogItemKey.BASIC for _cid, key in spawned)
    assert all(cid_ in {98, 99, 100} for cid_, _key in spawned)
    # the capture is recorded in the ledger (log + counter) but never
    # grants an item — the inventory stays empty
    assert (
        await full_bot.db.fetchval(
            "SELECT type FROM member_frog_log WHERE uid = 424242"
        )
        == "cluster"
    )
    assert (
        await full_bot.db.fetchval(
            "SELECT capture FROM member_frog WHERE uid = 424242"
        )
        == 1
    )
    assert (
        await full_bot.db.fetchval(
            "SELECT COUNT(*) FROM inventory WHERE uid = 424242"
        )
        == 0
    )


async def test_frog_catalog_is_a_per_user_collection_book(
    full_bot: CazzuBot,
) -> None:
    """``/frog catalog`` renders only the invoker's discovered species.

    Discovery rides the capture log: the driver seeds one Basic capture
    for the caller and a Pog capture for a different member, so the
    caller's book must render Basic in full and every other species as a
    nameless silhouette — Pog is never named, described, or given art.
    """
    from plugins.frogs import db as frog_db
    from plugins.frogs.species import SPECIES

    now = pendulum.now("UTC")
    await frog_db.add_capture_log(
        full_bot.db,
        424242,
        now,
        waited_for=1.0,
        species_key=FrogItemKey.BASIC,
    )
    await frog_db.add_capture_log(
        full_bot.db,
        555,
        now,
        waited_for=1.0,
        species_key=FrogItemKey.POG,
    )

    result = await run_slash(
        full_bot, "frog catalog", user_id=424242, timeout=10.0
    )

    assert result.exceptions == []
    first = result.first_response
    assert first is not None
    embed = first["embed"]
    assert embed.title == "tester's Frog Collection"
    desc = embed.description or ""
    assert "### Basic Frog\nThe most normalest frog of them all." in desc
    assert "Pog Frog" not in desc
    visible = [species for species in SPECIES if not species.hidden]
    assert desc.count("### ???") == len(visible) - 1
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["frog"]
