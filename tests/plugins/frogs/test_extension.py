"""Frogs extension + factory tests — spawn math, register, catalog, capture."""

from __future__ import annotations

from typing import Any

import hikari
import pendulum
import pytest

from cazzubot.bot import CazzuBot
from cazzubot.assets import asset_key
from cazzubot.errors import UserInputError
from cazzubot.models import FrogItemKey, FrogState
from cazzubot.tips import TIP_SETS
from plugins.frogs import FrogsPlugin, db as frog_db
from plugins.frogs import factory
from plugins.frogs.events import FrogCapturedEvent
from plugins.frogs.extension import (
    Catalog,
    DebugFreeze,
    Register,
    View,
)
from plugins.frogs.species import by_key
from plugins.misc.asset import MiscAsset
from tests.fakes import (
    FakeCache,
    FakeChannel,
    FakeContext,
    FakeGuild,
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


@pytest.fixture(autouse=True)
def _register_frog_tips() -> None:
    """Boot would fold the frogs plugin's tip_sets into the registry, but
    these tests drive commands on a plugin-less fixture bot — register the
    plugin's own sets explicitly (and restore after, since the registry is
    module-global across tests)."""
    from cazzubot.tips import register_tips, unregister_tips

    register_tips("frogs", FrogsPlugin.tip_sets)
    yield
    unregister_tips("frogs")


# -- profile / register / catalog ------------------------------------------


async def test_frog_view_no_captures_yet(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    await invoke_command(View(), ctx, member=author)
    assert (
        ctx.sent[-1].content
        == "No one has yet captured frogs in this server!"
    )


async def test_frog_view_lifetime_mode_uses_lifetime_ranked(
    bot: CazzuBot, ctx: FakeContext, author: FakeMember
) -> None:
    # a seasonal capture log makes the seasonal board non-empty, but the
    # lifetime counter is only rebuilt by sync_with_frog_logs — so mode=
    # "lifetime" falling back to the empty-board message proves the branch
    # read lifetime_ranked, not seasonal_ranked
    now = pendulum.now("UTC")
    await frog_db.add_capture_log(
        bot.db,
        author.id,
        now,
        waited_for=3.0,
        species_key=FrogItemKey.BASIC,
    )

    await invoke_command(View(), ctx, member=author, mode="lifetime")

    assert (
        ctx.sent[-1].content
        == "No one has yet captured frogs in this server!"
    )


async def test_frog_view_permit_footer_cycles_frog_tips(
    seeded_bot: CazzuBot,
    fake_guild: FakeGuild,
    author: FakeMember,
    channel: FakeChannel,
) -> None:
    """The capture-permit embed's footer draws from the shared frog tip set.

    The permit only renders on a populated board (empty states reply with
    plain text), so this seeds one capture and asserts the footer lands in
    the frog context's tips — the generic get_tip() set, not frogs-specific
    copy baked into this embed.
    """
    now = pendulum.now("UTC")
    await frog_db.add_capture_log(
        seeded_bot.db,
        author.id,
        now,
        waited_for=3.0,
        species_key=FrogItemKey.BASIC,
    )
    view_ctx = FakeContext(
        bot=seeded_bot,
        member=author,
        guild=fake_guild,
        channel=channel,
    )

    await invoke_command(View(), view_ctx, member=author)

    embed = view_ctx.sent[-1].embed
    assert embed is not None
    # no author field — the permit name moved to the embed title, and the
    # member's pfp is the thumbnail
    assert embed.author is None
    assert embed.title == f"{author.display_name}'s Frog Capture Permit"
    assert embed.thumbnail is not None
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["frog"]
    # no footer icon while the shared cirno emojis are unpublished
    assert embed.footer.icon is None
    # the tip must reference the real inventory command shapes
    joined = "\n".join(TIP_SETS["frog"])
    assert "/inventory info" in joined
    assert "/inventory consume" in joined


async def test_frog_view_inventory_snippet_normal_only_qty_ascending(
    seeded_bot: CazzuBot,
    fake_guild: FakeGuild,
    author: FakeMember,
    channel: FakeChannel,
) -> None:
    """The permit's Inventory section is a normal-frogs-only snippet.

    Frozen trophies are excluded, rows sort by quantity ascending, and the
    format is prose (``• label ×qty``) rather than /inventory view's
    inline-field grid.
    """
    now = pendulum.now("UTC")
    await frog_db.add_capture_log(
        seeded_bot.db,
        author.id,
        now,
        waited_for=3.0,
        species_key=FrogItemKey.BASIC,
    )
    # mixed stacks: two normal species (ascending 2 then 5), one frozen
    await frog_db.modify_inventory(
        seeded_bot.db, author.id, FrogItemKey.BASIC, FrogState.NORMAL, 5
    )
    await frog_db.modify_inventory(
        seeded_bot.db, author.id, FrogItemKey.POG, FrogState.NORMAL, 2
    )
    await frog_db.modify_inventory(
        seeded_bot.db, author.id, FrogItemKey.CLASSY, FrogState.FROZEN, 9
    )

    view_ctx = FakeContext(
        bot=seeded_bot,
        member=author,
        guild=fake_guild,
        channel=channel,
    )
    await invoke_command(View(), view_ctx, member=author)

    embed = view_ctx.sent[-1].embed
    assert embed is not None
    desc = embed.description
    assert desc is not None
    assert "**__Inventory__**" in desc
    # normal-only, qty ascending (2 before 5), no slot tokens, no state tags
    assert "Pog Frog ×`2`" in desc
    assert "Basic Frog ×`5`" in desc
    assert desc.index("Pog Frog ×`2`") < desc.index("Basic Frog ×`5`")
    assert "Frozen" not in desc
    assert "Classy Frog" not in desc
    assert "[" not in desc
    assert "(normal)" not in desc
    assert "(frozen)" not in desc


async def test_frog_view_inventory_snippet_no_frogs_yet_only_frozen(
    seeded_bot: CazzuBot,
    fake_guild: FakeGuild,
    author: FakeMember,
    channel: FakeChannel,
) -> None:
    """Only-frozen inventory → the "No frogs yet." empty state (normal-only)."""
    now = pendulum.now("UTC")
    await frog_db.add_capture_log(
        seeded_bot.db,
        author.id,
        now,
        waited_for=3.0,
        species_key=FrogItemKey.BASIC,
    )
    await frog_db.modify_inventory(
        seeded_bot.db, author.id, FrogItemKey.CLASSY, FrogState.FROZEN, 9
    )

    view_ctx = FakeContext(
        bot=seeded_bot,
        member=author,
        guild=fake_guild,
        channel=channel,
    )
    await invoke_command(View(), view_ctx, member=author)

    embed = view_ctx.sent[-1].embed
    assert embed is not None
    assert embed.description is not None
    assert "**__Inventory__**" in embed.description
    assert "No frogs yet." in embed.description
    assert "Classy Frog" not in embed.description


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


async def test_frog_debug_freeze_freezes_only_the_target_user(
    bot: CazzuBot,
    ctx: FakeContext,
    fake_guild: FakeGuild,
) -> None:
    """/frog debug freeze <member> runs the per-user quarterly rollover.

    Owner-gated (hooks=[utils.OWNER_ONLY]); the target user's normal
    stacks move to frozen while the invoker's stacks and both users'
    Frog Remains stay put — the same semantics as the scheduler's global
    ``season_reset_frogs``, scoped to one user.
    """
    target = FakeMember(id=999, name="frex", guild=fake_guild)
    for key, qty in ((FrogItemKey.BASIC, 3), (FrogItemKey.POG, 2)):
        await frog_db.modify_inventory(
            bot.db, target.id, key, FrogState.NORMAL, qty
        )
    # the invoker has their own normal frog + both hold Frog Remains
    await frog_db.modify_inventory(
        bot.db, ctx.member.id, FrogItemKey.CLASSY, FrogState.NORMAL, 4
    )
    await bot.inventory.add(target.id, "remains", 2)
    await bot.inventory.add(ctx.member.id, "remains", 3)

    await invoke_command(DebugFreeze(), ctx, member=target)

    # target frozen; invoker + remains untouched
    assert (
        await frog_db.get_inventory(bot.db, target.id, FrogItemKey.BASIC)
        == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, target.id, FrogItemKey.BASIC, FrogState.FROZEN
        )
        == 3
    )
    assert (
        await frog_db.get_inventory(bot.db, target.id, FrogItemKey.POG)
        == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, target.id, FrogItemKey.POG, FrogState.FROZEN
        )
        == 2
    )
    assert (
        await frog_db.get_inventory(
            bot.db, ctx.member.id, FrogItemKey.CLASSY
        )
        == 4
    )
    assert (
        await frog_db.get_inventory(
            bot.db, ctx.member.id, FrogItemKey.CLASSY, FrogState.FROZEN
        )
        == 0
    )
    assert await bot.inventory.get(target.id, "remains") == 2
    assert await bot.inventory.get(ctx.member.id, "remains") == 3
    # the reply summarizes what froze
    assert ctx.sent[-1].content == (
        "✓ Froze frex's frogs: Basic Frog ×3, Pog Frog ×2"
    )


async def test_frog_debug_freeze_no_normal_frogs_is_a_noop(
    bot: CazzuBot,
    ctx: FakeContext,
    fake_guild: FakeGuild,
) -> None:
    """A user with no normal frogs gets a quiet success — nothing to move."""
    target = FakeMember(id=999, name="frex", guild=fake_guild)
    await frog_db.modify_inventory(
        bot.db, target.id, FrogItemKey.CLASSY, FrogState.FROZEN, 7
    )

    await invoke_command(DebugFreeze(), ctx, member=target)

    assert (
        await frog_db.get_inventory(
            bot.db, target.id, FrogItemKey.CLASSY, FrogState.FROZEN
        )
        == 7
    )
    assert ctx.sent[-1].content == "✓ frex has no normal frogs to freeze."


async def test_frog_catalog_lists_all_frogmd_species(
    bot: CazzuBot,
    ctx: FakeContext,
) -> None:
    await invoke_command(Catalog(), ctx)

    embed = ctx.sent[-1].embed
    assert embed is not None
    assert embed.title == "Frog Species Catalog"
    names = [field.name for field in embed.fields]
    assert len(names) == 5
    assert any("Basic Frog" in name for name in names)
    assert any("Pog Frog" in name for name in names)
    assert any("Froggers Frog" in name for name in names)
    assert any("Classy Frog" in name for name in names)
    assert any("Cluster Frog" in name for name in names)
    # name + art + description only — no rarity, and the item's own
    # effects (exp/consume) belong to `/inventory info`, not the catalog
    descriptions = {
        "Basic Frog": "The most normalest frog of them all.",
        "Pog Frog": "A frog with a pog.",
        "Froggers Frog": "A frog with a poggers.",
        "Classy Frog": "A frog with rather refined tastes.",
        "Cluster Frog": "Be careful with this one… she's… spawning!",
    }
    for field in embed.fields:
        # species names render bolded (markdown **) as the field label
        assert field.name.startswith("**") and field.name.endswith("**")
        assert field.name.strip("*") in descriptions
        assert "Rarity" not in field.value
        assert "Consume:" not in field.value
        assert "exp" not in field.value
    # the catalog shares /frog view's cycling frog-tip footer
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["frog"]
    # no footer icon while the shared cirno emojis are unpublished
    assert embed.footer.icon is None


async def test_frog_catalog_footer_icon_pulls_a_random_misc_emoji(
    bot: CazzuBot,
    ctx: FakeContext,
) -> None:
    """The tip footer's icon is a random published cirno emoji's CDN URL.

    Every ``MiscAsset`` member is published with a distinct emoji id, so
    whichever member the per-render random pick lands on, the footer icon
    resolves to that emoji's CDN URL (patching the shared ``random``
    module would also hijack ``tips.get_tip`` — the footer text — so the
    test asserts membership instead of pinning one member).
    """
    for i, asset in enumerate(MiscAsset):
        await bot.db.execute(
            "UPDATE asset SET url = ? WHERE key = ?",
            f"<:cirno:{1100 + i}>",
            asset_key(asset),
        )

    await invoke_command(Catalog(), ctx)

    embed = ctx.sent[-1].embed
    assert embed is not None
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["frog"]
    assert embed.footer.icon is not None
    assert str(embed.footer.icon.url) in {
        f"https://cdn.discordapp.com/emojis/{1100 + i}.png"
        for i in range(len(tuple(MiscAsset)))
    }


# -- capture menu -----------------------------------------------------------


async def test_frog_catch_captures_once(
    seeded_bot: CazzuBot, author: FakeMember
) -> None:
    menu = factory.FrogCatchMenu(
        seeded_bot, 99, FrogItemKey.BASIC, persist=30
    )
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
    created_msg = created[0]
    assert created_msg.create_kwargs is not None
    assert created_msg.channel_id == 99
    # the capture announcement is the hardcoded built-in embed — no
    # frog.message template involved
    embed = created_msg.embeds[0]
    assert embed.title == "Congrats on your catch!"
    # least-permissive: only the catcher is pinged — explicit user list,
    # no role/@everyone parsing
    assert created_msg.create_kwargs["user_mentions"] == [_UID]
    assert created_msg.create_kwargs["role_mentions"] is hikari.UNDEFINED
    assert (
        created_msg.create_kwargs["mentions_everyone"] is hikari.UNDEFINED
    )
    assert (
        await frog_db.get_inventory(seeded_bot.db, _UID, FrogItemKey.BASIC)
        == 1
    )
    # the message content carries ONLY the catcher's mention (that is
    # where the ping lives) — the counts ride in the embed below
    assert created_msg.content == f"<@{_UID}>"
    assert embed.description is not None
    # a first capture: species stack, season, and total all tick 0 -> 1
    assert "+1 to froggies" in embed.description
    assert "**Basic Frog**: `0` -> `1`" in embed.description
    assert "**Seasonal Captures**: `0` -> `1`" in embed.description
    assert "**Total Froggies**: `0` -> `1`" in embed.description
    # capture log records the species key
    assert (
        await seeded_bot.db.fetchval(
            "SELECT type FROM member_frog_log WHERE uid = ?", _UID
        )
        == "basic"
    )

    # second click is denied
    await menu_button(menu).callback(mctx)
    assert mctx.sent[-1].content == "This frog was already caught."
    assert mctx.sent[-1].ephemeral is True


async def test_frog_catch_sends_hardcoded_embed(
    seeded_bot: CazzuBot, author: FakeMember
) -> None:
    """Every capture sends the hardcoded announcement embed — never a
    template-driven or blank message. The published species-art emoji
    renders INSIDE the embed, beside the species' old→new count; the
    message content carries ONLY the catcher's mention (the ping)."""
    # simulate a published art emoji (offline seeds have NULL url — the
    # "not published yet" state exercised by the fallback test below)
    await seeded_bot.db.execute(
        "UPDATE asset SET url = ? WHERE key = ?",
        "<:frog_basic:123456789012345678>",
        "FrogAsset.FROG_BASIC",
    )
    menu = factory.FrogCatchMenu(
        seeded_bot, 99, FrogItemKey.BASIC, persist=30
    )
    mctx = FakeMenuContext(
        FakeInteraction(id=1, member=author, channel_id=99)
    )
    await menu_button(menu).callback(mctx)

    created = rest_of(seeded_bot).created
    assert len(created) == 1
    created_msg = created[0]
    assert created_msg.create_kwargs is not None
    # the catcher's mention + ping live on the message content — and
    # nothing else does (Discord does not resolve pings inside embeds)
    assert created_msg.content == f"<@{_UID}>"
    embed = created_msg.embeds[0]
    assert embed.title == "Congrats on your catch!"
    # the embed carries the counts and the art emoji — and no mention
    assert embed.description is not None
    assert f"<@{_UID}>" not in embed.description
    assert "+1 to froggies" in embed.description
    # the published art emoji renders inside the embed, beside the species
    assert "<:frog_basic:123456789012345678>" in embed.description
    assert "**Basic Frog**: `0` -> `1`" in embed.description
    assert "**Seasonal Captures**: `0` -> `1`" in embed.description
    assert "**Total Froggies**: `0` -> `1`" in embed.description
    # the thumbnail references the CATCH_BANNER media asset (unpublished
    # in offline seeds → no thumbnail) + the cycling footer tip (shared
    # frog set), with the catcher's avatar as the footer icon
    assert embed.thumbnail is None
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["frog"]
    assert embed.footer.icon is not None
    assert str(embed.footer.icon.url) == (
        f"https://example.com/avatar/{_UID}.png"
    )
    # and the hardcoded embed pings only the catcher explicitly
    assert created_msg.create_kwargs["user_mentions"] == [_UID]
    assert created_msg.create_kwargs["role_mentions"] is hikari.UNDEFINED
    # and the +1 still hit inventory
    assert (
        await frog_db.get_inventory(seeded_bot.db, _UID, FrogItemKey.BASIC)
        == 1
    )


async def test_frog_catch_embed_omits_emoji_when_art_unpublished(
    seeded_bot: CazzuBot, author: FakeMember
) -> None:
    """Unpublished species art adds no emoji to the embed — and never the
    literal "None" (mirrors the spawn message's fallback)."""
    menu = factory.FrogCatchMenu(
        seeded_bot, 99, FrogItemKey.BASIC, persist=30
    )
    mctx = FakeMenuContext(
        FakeInteraction(id=1, member=author, channel_id=99)
    )
    await menu_button(menu).callback(mctx)

    created = rest_of(seeded_bot).created
    assert len(created) == 1
    created_msg = created[0]
    assert created_msg.create_kwargs is not None
    # the content is the mention only — no emoji fallback text anywhere
    assert created_msg.content == f"<@{_UID}>"
    embed = created_msg.embeds[0]
    assert embed.description is not None
    assert "<:frog_basic:" not in embed.description
    assert "**Basic Frog**: `0` -> `1`" in embed.description
    assert "None" not in embed.description
    # the mention + ping survive the no-emoji fallback
    assert created_msg.create_kwargs["user_mentions"] == [_UID]
    assert created_msg.create_kwargs["role_mentions"] is hikari.UNDEFINED


async def test_frog_catch_ignores_leftover_message_setting(
    seeded_bot: CazzuBot, author: FakeMember
) -> None:
    """A leftover ``frog.message`` setting (from before the template path
    was removed) is inert: the capture announcement is ALWAYS the
    hardcoded embed, and the catcher is always pinged."""
    await seeded_bot.settings.set(
        "frog.message", {"content": "caught {mention}"}
    )
    menu = factory.FrogCatchMenu(
        seeded_bot, 99, FrogItemKey.BASIC, persist=30
    )
    mctx = FakeMenuContext(
        FakeInteraction(id=1, member=author, channel_id=99)
    )
    await menu_button(menu).callback(mctx)

    created = rest_of(seeded_bot).created
    assert len(created) == 1
    created_msg = created[0]
    assert created_msg.create_kwargs is not None
    # the mention + ping stay on the content; the embed never carries it
    assert created_msg.content == f"<@{_UID}>"
    embed = created_msg.embeds[0]
    assert embed.title == "Congrats on your catch!"
    assert embed.description is not None
    assert f"<@{_UID}>" not in embed.description
    assert "+1 to froggies" in embed.description
    assert "**Basic Frog**: `0` -> `1`" in embed.description
    assert created_msg.create_kwargs["user_mentions"] == [_UID]
    assert created_msg.create_kwargs["role_mentions"] is hikari.UNDEFINED


async def test_frog_catch_embed_thumbnail_references_banner_asset(
    seeded_bot: CazzuBot, author: FakeMember
) -> None:
    """The capture embed's thumbnail references the CATCH_BANNER media
    asset (plugins/assets/caught.png) — publishing it makes its CDN URL
    the embed's thumbnail, not a hardcoded image."""
    await seeded_bot.db.execute(
        "UPDATE asset SET url = ? WHERE key = ?",
        "https://cdn.example/catch_banner.png",
        "FrogAsset.CATCH_BANNER",
    )
    menu = factory.FrogCatchMenu(
        seeded_bot, 99, FrogItemKey.BASIC, persist=30
    )
    mctx = FakeMenuContext(
        FakeInteraction(id=1, member=author, channel_id=99)
    )
    await menu_button(menu).callback(mctx)

    embed = rest_of(seeded_bot).created[0].embeds[0]
    assert embed.thumbnail is not None
    assert embed.thumbnail.url == "https://cdn.example/catch_banner.png"


async def test_frog_catch_emits_captured_event(
    seeded_bot: CazzuBot, author: FakeMember
) -> None:
    """Observers (badges) see the completed capture via the event bus."""
    received: list[FrogCapturedEvent] = []

    async def on_captured(event: FrogCapturedEvent) -> None:
        received.append(event)

    seeded_bot.events.on(FrogCapturedEvent, on_captured)

    menu = factory.FrogCatchMenu(
        seeded_bot, 99, FrogItemKey.BASIC, persist=30
    )
    mctx = FakeMenuContext(
        FakeInteraction(id=1, member=author, channel_id=99)
    )
    await menu_button(menu).callback(mctx)

    assert len(received) == 1
    assert received[0].uid == _UID
    assert received[0].species_key is FrogItemKey.BASIC


async def test_frog_catch_button_carries_species(
    seeded_bot: CazzuBot, author: FakeMember
) -> None:
    """The custom_id embeds the species so the boot sweep still matches."""
    menu = factory.FrogCatchMenu(
        seeded_bot, 99, FrogItemKey.BASIC, persist=30
    )
    button = menu_button(menu)
    assert button.custom_id == "frog:catch:99:basic"
    # the frog's lifetime is carried for catch behaviors (the cluster
    # burst spawns children living the same persist)
    assert menu.persist == 30
    assert factory._is_frog_message(  # pyright: ignore[reportPrivateUsage]
        _frog_message(99, 1, "frog:catch:99:basic"), 99
    )
    # channel prefixes stay apart: frog:catch:99: never matches channel 999
    assert not factory._is_frog_message(  # pyright: ignore[reportPrivateUsage]
        _frog_message(999, 1, "frog:catch:99:basic"), 999
    )


async def test_on_frog_due_reschedules_and_despawns(
    seeded_bot: CazzuBot,
    channel: FakeChannel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await frog_db.set_enabled(seeded_bot.settings, True)
    payload = {
        "cid": channel.id,
        "interval": 120,
        "persist": 1,
        "fuzzy": 0.5,
    }
    # five species roll by weight now — pin Basic so the spawn (and its
    # deleted message) is deterministic
    monkeypatch.setattr(
        factory, "roll_species", lambda: by_key(FrogItemKey.BASIC)
    )

    await factory.on_frog_due(seeded_bot, payload)

    # next spawn was pre-rolled before this one spawned
    assert len(await seeded_bot.scheduler.get("frog")) == 1
    # frog message sent (a rolled species), then removed when bored
    assert len(channel.sent) == 1
    assert channel.sent[0]["content"] == "Basic Frog"
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
    run_at = rows[0].run_at  # already a DateTime at the model boundary
    # interval ± 50% from the fire instant — the upper bound is what
    # rejects the old despawn-anchored design (it would arm ≥ now+660)
    assert before.add(seconds=60) <= run_at
    assert run_at <= pendulum.now("UTC").add(seconds=180)


def _frog_message(
    cid: int, mid: int, custom_id: str | None
) -> FakeMessage:
    """A message whose components carry (or lack) a catch button."""
    from types import SimpleNamespace

    msg = FakeMessage(id=mid, channel_id=cid, guild_id=2)
    if custom_id is not None:
        button = SimpleNamespace(custom_id=custom_id)
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
            channel.id,
            mid,
            f"frog:catch:{channel.id}:basic" if with_button else None,
        )

    await factory.cleanup_dangling_frogs(seeded_bot)

    expected = [(channel.id, mid)] if with_message and with_button else []
    assert rest_of(seeded_bot).deleted == expected
    assert await frog_db.get_frog_messages(seeded_bot.db) == []
