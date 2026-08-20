"""Asset core — typed declarations, derived keys, reconcile, CDN sync."""

from __future__ import annotations

import hashlib
import logging
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import hikari

from cazzubot import AssetKind, AssetSpec, Assets, Plugin
from cazzubot.assets import (
    SCHEMA,
    AssetError,
    _EMOJI_CREATE_DELAY,
    _emoji_id_from_ref,
    _emoji_name_from_key,
    _is_emoji_ref,
    _message_id,
    asset_key,
)
from cazzubot.db import Database
from tests.fakes import FakeAttachment, FakeMessage, FakeRest


@pytest.fixture
async def asset_db(db: Database) -> Database:
    """A bare Database with the asset registry schema applied."""
    await db.run_schema(SCHEMA)
    return db


class _FrogAsset(Enum):
    LEAF_FROG = AssetSpec(
        kind=AssetKind.SPECIES, path="assets/leaf_frog.png"
    )
    CLASSY_FROG = AssetSpec(
        kind=AssetKind.SPECIES, path="assets/classy_frog.webp"
    )


class _AssetsPlugin(Plugin):
    name = "frogs"
    asset_decl = _FrogAsset


class _FakeBot:
    """Minimal bot surface the Assets service touches (db/plugins/rest)."""

    def __init__(self, db: Database, plugins_dir: str) -> None:
        self.db = db
        self.plugins: list[Plugin] = []
        self.rest = SimpleNamespace(create_message=_no_message)
        self._subscribed: list[object] = []

    def subscribe(self, _event_type: object, callback: object) -> None:
        self._subscribed.append(callback)


async def _no_message(*_args: object, **_kwargs: object) -> FakeMessage:
    raise AssertionError("no asset channel — sync must not upload")


def _assets(
    db: Database,
    plugins_dir: str,
    *,
    channel_id: int | None = None,
    guild_id: int | None = None,
) -> Assets:
    fake = _FakeBot(db, plugins_dir)
    fake.plugins = [_AssetsPlugin()]
    config = SimpleNamespace(
        asset_channel_id=channel_id, asset_guild_id=guild_id
    )
    return Assets(cast(Any, fake), cast(Any, config), plugins_dir)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_art(root: Path, name: str, content: bytes) -> Path:
    path = root / "frogs" / "assets" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_asset_key_is_derived_from_enum_identity() -> None:
    """The registry key comes from the enum — never a hand-written string."""
    assert asset_key(_FrogAsset.LEAF_FROG) == "_FrogAsset.LEAF_FROG"
    assert asset_key(_FrogAsset.CLASSY_FROG) == "_FrogAsset.CLASSY_FROG"


async def test_reconcile_registers_and_publishes(
    asset_db: Database, tmp_path: Path
) -> None:
    """Declared files land in the registry; a configured channel publishes
    them and ``get`` returns the stored CDN URL."""
    _write_art(tmp_path, "leaf_frog.png", b"leaf bytes")
    _write_art(tmp_path, "classy_frog.webp", b"classy bytes")
    assets = _assets(asset_db, str(tmp_path), channel_id=777)

    await assets.reconcile()
    assert await asset_db.fetchval("SELECT COUNT(*) FROM asset") == 2
    assert await asset_db.fetchval("SELECT url FROM asset") is None
    assert await asset_db.fetchval(
        "SELECT sha256 FROM asset WHERE key = ?",
        asset_key(_FrogAsset.LEAF_FROG),
    ) == _sha256_bytes(b"leaf bytes")

    async def _upload(_channel_id: int, **_: object) -> FakeMessage:
        message = FakeMessage(id=1, channel_id=_channel_id)
        message.attachments = [
            FakeAttachment(
                id=1,
                filename="leaf_frog.png",
                url="https://cdn.example.com/leaf_frog.png",
            )
        ]
        return message

    cast(Any, assets.bot).rest = SimpleNamespace(create_message=_upload)
    await assets.sync_cdn(cast(Any, None))

    assert (
        await assets.get(_FrogAsset.LEAF_FROG)
        == "https://cdn.example.com/leaf_frog.png"
    )


async def test_reconcile_changed_file_resyncs(
    asset_db: Database, tmp_path: Path
) -> None:
    """An edited art file re-queues the row for CDN sync (url cleared)."""
    path = _write_art(tmp_path, "leaf_frog.png", b"v1")
    _write_art(tmp_path, "classy_frog.webp", b"v1")
    assets = _assets(asset_db, str(tmp_path), channel_id=None)
    await assets.reconcile()
    await asset_db.execute(
        "UPDATE asset SET url = 'https://old' WHERE key = ?",
        asset_key(_FrogAsset.LEAF_FROG),
    )

    path.write_bytes(b"v2")
    await assets.reconcile()

    row = await asset_db.fetchone(
        "SELECT sha256, url FROM asset WHERE key = ?",
        asset_key(_FrogAsset.LEAF_FROG),
    )
    assert row is not None
    assert row["url"] is None  # re-queued
    assert row["sha256"] == _sha256_bytes(b"v2")


async def test_reconcile_missing_file_aborts(
    asset_db: Database, tmp_path: Path
) -> None:
    """A declared asset whose file is gone refuses to boot (fail-fast)."""
    _write_art(tmp_path, "classy_frog.webp", b"classy bytes")
    assets = _assets(asset_db, str(tmp_path), channel_id=None)
    with pytest.raises(AssetError, match="LEAF_FROG"):
        await assets.reconcile()


async def test_sync_without_channel_skips(
    asset_db: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No channel configured: boot warning, no uploads, rows stay null."""
    _write_art(tmp_path, "leaf_frog.png", b"leaf")
    _write_art(tmp_path, "classy_frog.webp", b"classy")
    assets = _assets(asset_db, str(tmp_path), channel_id=None)
    await assets.reconcile()

    with caplog.at_level(logging.WARNING, logger="cazzubot.assets"):
        await assets.sync_cdn(cast(Any, None))

    assert any(
        "skipping asset sync" in record.message
        for record in caplog.records
    )
    assert (
        await asset_db.fetchval(
            "SELECT COUNT(*) FROM asset WHERE url IS NOT NULL"
        )
        == 0
    )


async def test_get_unknown_asset_raises(
    asset_db: Database, tmp_path: Path
) -> None:
    _write_art(tmp_path, "leaf_frog.png", b"leaf")
    _write_art(tmp_path, "classy_frog.webp", b"classy")
    assets = _assets(asset_db, str(tmp_path), channel_id=None)
    await assets.reconcile()

    class _GhostAsset(Enum):
        GHOST = AssetSpec(kind=AssetKind.SPECIES, path="assets/ghost.png")

    with pytest.raises(KeyError, match="GHOST"):
        await assets.get(_GhostAsset.GHOST)


# -- pruning + liveness (the registry mirrors the code and the channel) -----


_LeafOnly = Enum(
    # same class name as _FrogAsset — a real deletion keeps the enum's
    # name (and therefore its derived keys) stable, only members change
    "_FrogAsset",
    {
        "LEAF_FROG": AssetSpec(
            kind=AssetKind.SPECIES, path="assets/leaf_frog.png"
        )
    },
)


def _url(channel: int, message: int, name: str) -> str:
    return (
        f"https://cdn.example.com/attachments/{channel}/{message}/{name}"
    )


async def test_reconcile_prunes_undeclared_asset(
    asset_db: Database, tmp_path: Path
) -> None:
    """A declaration deleted from code drops its registry row."""
    _write_art(tmp_path, "leaf_frog.png", b"leaf")
    _write_art(tmp_path, "classy_frog.webp", b"classy")
    assets = _assets(asset_db, str(tmp_path), channel_id=None)
    await assets.reconcile()
    assert await asset_db.fetchval("SELECT COUNT(*) FROM asset") == 2

    assets.bot.plugins[0].asset_decl = _LeafOnly
    await assets.reconcile()

    assert await asset_db.fetchval("SELECT COUNT(*) FROM asset") == 1
    with pytest.raises(KeyError, match="CLASSY"):
        await assets.get(_FrogAsset.CLASSY_FROG)
    # the surviving row is intact — unpublished (no channel), not gone
    assert await assets.get(_FrogAsset.LEAF_FROG) is None


async def test_pruned_asset_cdn_message_is_deleted(
    asset_db: Database, tmp_path: Path
) -> None:
    """Prune queues the orphaned CDN message; the sync deletes it."""
    _write_art(tmp_path, "leaf_frog.png", b"leaf")
    _write_art(tmp_path, "classy_frog.webp", b"classy")
    assets = _assets(asset_db, str(tmp_path), channel_id=777)
    rest = FakeRest()
    cast(Any, assets.bot).rest = rest
    await assets.reconcile()
    await asset_db.execute(
        "UPDATE asset SET url = ? WHERE key = ?",
        _url(777, 111, "leaf.png"),
        asset_key(_FrogAsset.LEAF_FROG),
    )
    await asset_db.execute(
        "UPDATE asset SET url = ? WHERE key = ?",
        _url(777, 222, "classy.webp"),
        asset_key(_FrogAsset.CLASSY_FROG),
    )
    # leaf's publication is alive; classy's is about to be orphaned
    rest.messages[(777, 111)] = FakeMessage(id=111, channel_id=777)

    assets.bot.plugins[0].asset_decl = _LeafOnly
    await assets.reconcile()
    await assets.sync_cdn(cast(Any, None))

    assert (777, 222) in rest.deleted  # orphaned message gone
    assert (777, 111) not in rest.deleted  # live message untouched
    assert await asset_db.fetchval("SELECT COUNT(*) FROM asset") == 1
    assert (
        await asset_db.fetchval("SELECT url FROM asset")
        == _url(777, 111, "leaf.png")  # verification kept it
    )


async def test_deleted_cdn_message_republishes(
    asset_db: Database, tmp_path: Path
) -> None:
    """A CDN message deleted by hand re-publishes on the next sync."""
    _write_art(tmp_path, "leaf_frog.png", b"leaf")
    _write_art(tmp_path, "classy_frog.webp", b"classy v2")
    assets = _assets(asset_db, str(tmp_path), channel_id=777)
    rest = FakeRest()
    cast(Any, assets.bot).rest = rest
    await assets.reconcile()
    await asset_db.execute(
        "UPDATE asset SET url = ? WHERE key = ?",
        _url(777, 111, "leaf.png"),
        asset_key(_FrogAsset.LEAF_FROG),
    )
    await asset_db.execute(
        "UPDATE asset SET url = ? WHERE key = ?",
        _url(777, 222, "classy.webp"),
        asset_key(_FrogAsset.CLASSY_FROG),
    )
    rest.messages[(777, 111)] = FakeMessage(id=111, channel_id=777)
    # classy's message is NOT recorded — someone deleted it

    created: list[FakeMessage] = []

    async def _upload(_channel_id: int, **_: object) -> FakeMessage:
        message = FakeMessage(id=333, channel_id=_channel_id)
        message.attachments = [
            FakeAttachment(
                id=9,
                filename="classy.webp",
                url=_url(777, 333, "classy.webp"),
            )
        ]
        created.append(message)
        return message

    cast(Any, assets.bot).rest = SimpleNamespace(
        create_message=_upload,
        fetch_message=rest.fetch_message,
        delete_message=rest.delete_message,
    )
    await assets.sync_cdn(cast(Any, None))

    assert len(created) == 1  # only the dead one re-uploaded
    assert await asset_db.fetchval(
        "SELECT url FROM asset WHERE key = ?",
        asset_key(_FrogAsset.CLASSY_FROG),
    ) == _url(777, 333, "classy.webp")


def test_message_id_parses_attachment_url() -> None:
    assert (
        _message_id(
            "https://cdn.example.com/attachments/777/222/classy.webp"
        )
        == 222
    )
    assert _message_id("https://cdn.example.com/not-an-attachment") is None


# -- emoji-kind assets (the asset child-guild) ------------------------------


class _FakeEmoji:
    """The bits of a guild emoji the sync reads back (its id)."""

    def __init__(self, eid: int) -> None:
        self.id = eid


class _EmojiAsset(Enum):
    FROG_GLYPH = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/frog_emoji.png"
    )
    CLASSY_GLYPH = AssetSpec(
        kind=AssetKind.EMOJI, path="assets/classy_emoji.webp"
    )


class _EmojiPlugin(Plugin):
    name = "emojis"
    asset_decl = _EmojiAsset


def _write_glyph(root: Path, name: str, content: bytes) -> Path:
    path = root / "emojis" / "assets" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_glyphs(root: Path) -> None:
    """Write every file the emoji declaration needs (reconcile requires all)."""
    _write_glyph(root, "frog_emoji.png", b"frog glyph bytes")
    _write_glyph(root, "classy_emoji.webp", b"classy glyph bytes")


def test_emoji_ref_helpers() -> None:
    """``<:name:id>`` / ``<a:name:id>`` parse; CDN URLs do not."""
    assert _is_emoji_ref("<:leaf:123>")
    assert _is_emoji_ref("<a:leaf:123>")
    assert not _is_emoji_ref("https://cdn.example.com/leaf.png")
    assert _emoji_id_from_ref("<:leaf:123>") == 123
    assert _emoji_id_from_ref("<a:leaf:123>") == 123
    assert _emoji_id_from_ref("https://cdn.example.com/leaf.png") is None


def test_emoji_name_is_derived_from_asset_key() -> None:
    """Names are lowercase [a-z0-9_], 2-32 chars, no leading/trailing _."""
    assert _emoji_name_from_key("_EmojiAsset.FROG_GLYPH") == "frog_glyph"
    assert _emoji_name_from_key("FrogAsset.MY Bad NAME!!") == "mybadname"
    assert _emoji_name_from_key("X._LEAD_TRAIL_") == "lead_trail"
    assert len(_emoji_name_from_key("A." + "z" * 60)) <= 32


async def test_emoji_asset_publishes_as_guild_emoji(
    asset_db: Database, tmp_path: Path
) -> None:
    """An EMOJI asset creates a guild emoji and stores its ``<:name:id>``."""
    _write_glyphs(tmp_path)
    fake = _FakeBot(asset_db, str(tmp_path))
    fake.plugins = [_EmojiPlugin()]
    created: list[tuple[int, str]] = []

    async def _create(
        guild_id: int, *, name: str, image: object, **_: object
    ) -> _FakeEmoji:
        created.append((guild_id, name))
        return _FakeEmoji(555 if name == "frog_glyph" else 777)

    cast(Any, fake).rest = SimpleNamespace(create_emoji=_create)
    assets = Assets(
        cast(Any, fake),
        cast(
            Any, SimpleNamespace(asset_channel_id=None, asset_guild_id=888)
        ),
        str(tmp_path),
    )

    await assets.reconcile()
    await assets.sync_cdn(cast(Any, None))

    assert (888, "frog_glyph") in created
    assert await assets.get(_EmojiAsset.FROG_GLYPH) == "<:frog_glyph:555>"
    assert (
        await assets.get(_EmojiAsset.CLASSY_GLYPH) == "<:classy_glyph:777>"
    )


async def test_emoji_asset_skips_when_guild_unset(
    asset_db: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No asset guild: emoji rows are skipped with a warning, url stays null."""
    _write_glyphs(tmp_path)
    fake = _FakeBot(asset_db, str(tmp_path))
    fake.plugins = [_EmojiPlugin()]
    cast(Any, fake).rest = SimpleNamespace(create_emoji=_no_message)
    assets = Assets(
        cast(Any, fake),
        cast(
            Any, SimpleNamespace(asset_channel_id=777, asset_guild_id=None)
        ),
        str(tmp_path),
    )
    await assets.reconcile()

    with caplog.at_level(logging.WARNING, logger="cazzubot.assets"):
        await assets.sync_cdn(cast(Any, None))

    assert any(
        "ASSET_GUILD_ID" in record.message for record in caplog.records
    )
    assert (
        await asset_db.fetchval(
            "SELECT url FROM asset WHERE key = ?",
            asset_key(_EmojiAsset.FROG_GLYPH),
        )
        is None
    )


async def test_emoji_file_too_large_is_skipped(
    asset_db: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An emoji image over Discord's cap is logged and not created."""
    _write_glyphs(tmp_path)
    _write_glyph(tmp_path, "frog_emoji.png", b"x" * (256 * 1024 + 1))
    fake = _FakeBot(asset_db, str(tmp_path))
    fake.plugins = [_EmojiPlugin()]
    created: list[str] = []

    async def _create(
        guild_id: int, *, name: str, **_: object
    ) -> _FakeEmoji:
        created.append(name)
        return _FakeEmoji(1)

    cast(Any, fake).rest = SimpleNamespace(create_emoji=_create)
    assets = Assets(
        cast(Any, fake),
        cast(
            Any, SimpleNamespace(asset_channel_id=None, asset_guild_id=888)
        ),
        str(tmp_path),
    )
    await assets.reconcile()
    await assets.sync_cdn(cast(Any, None))

    # the oversized frog is skipped; only its healthy classy sibling created
    assert "frog_glyph" not in created
    assert created == ["classy_glyph"]
    assert (
        await asset_db.fetchval(
            "SELECT url FROM asset WHERE key = ?",
            asset_key(_EmojiAsset.FROG_GLYPH),
        )
        is None
    )


async def test_emoji_hash_change_deletes_and_recreates(
    asset_db: Database, tmp_path: Path
) -> None:
    """A changed emoji file deletes the old guild emoji and creates a new one."""
    _write_glyphs(tmp_path)
    _write_glyph(tmp_path, "frog_emoji.png", b"v1")
    fake = _FakeBot(asset_db, str(tmp_path))
    fake.plugins = [_EmojiPlugin()]

    async def _create(guild_id: int, **_: object) -> _FakeEmoji:
        return _FakeEmoji(555 if guild_id else 555)

    deleted: list[int] = []
    cast(Any, fake).rest = SimpleNamespace(
        create_emoji=_create,
        delete_emoji=lambda guild, emoji: deleted.append(emoji),
        fetch_emoji=lambda guild, emoji: _FakeEmoji(emoji),
    )
    assets = Assets(
        cast(Any, fake),
        cast(
            Any, SimpleNamespace(asset_channel_id=None, asset_guild_id=888)
        ),
        str(tmp_path),
    )
    await assets.reconcile()
    await asset_db.execute(
        "UPDATE asset SET url = '<:frog_glyph:999>' WHERE key = ?",
        asset_key(_EmojiAsset.FROG_GLYPH),
    )

    # change the file — reconcile queues the old emoji for deletion
    _write_glyph(tmp_path, "frog_emoji.png", b"v2")
    await assets.reconcile()
    assert assets._pending_deletes == ["<:frog_glyph:999>"]

    await assets.sync_cdn(cast(Any, None))
    assert deleted == [999]  # old emoji gone
    assert await assets.get(_EmojiAsset.FROG_GLYPH) == "<:frog_glyph:555>"


async def test_dead_guild_emoji_republishes(
    asset_db: Database, tmp_path: Path
) -> None:
    """A guild emoji deleted by hand re-publishes on the next sync."""
    _write_glyphs(tmp_path)
    fake = _FakeBot(asset_db, str(tmp_path))
    fake.plugins = [_EmojiPlugin()]

    async def _create(guild_id: int, **_: object) -> _FakeEmoji:
        return _FakeEmoji(444)

    async def _raise_not_found(guild: object, emoji: object) -> _FakeEmoji:
        headers: dict[str, str] = {}
        raise hikari.NotFoundError(
            url="https://example.com", headers=headers, raw_body=None
        )

    cast(Any, fake).rest = SimpleNamespace(
        create_emoji=_create,
        fetch_emoji=_raise_not_found,
    )
    assets = Assets(
        cast(Any, fake),
        cast(
            Any, SimpleNamespace(asset_channel_id=None, asset_guild_id=888)
        ),
        str(tmp_path),
    )
    await assets.reconcile()
    await asset_db.execute(
        "UPDATE asset SET url = '<:frog_glyph:9>' WHERE key = ?",
        asset_key(_EmojiAsset.FROG_GLYPH),
    )

    await assets.sync_cdn(cast(Any, None))
    assert await assets.get(_EmojiAsset.FROG_GLYPH) == "<:frog_glyph:444>"


async def test_emoji_creates_are_throttled(
    asset_db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Consecutive emoji creates in one pass sleep between them."""
    _write_glyph(tmp_path, "frog_emoji.png", b"f")
    _write_glyph(tmp_path, "classy_emoji.webp", b"c")
    fake = _FakeBot(asset_db, str(tmp_path))
    fake.plugins = [_EmojiPlugin()]

    async def _create(guild_id: int, **_: object) -> _FakeEmoji:
        return _FakeEmoji(guild_id)

    cast(Any, fake).rest = SimpleNamespace(create_emoji=_create)
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("cazzubot.assets.asyncio.sleep", _fake_sleep)
    assets = Assets(
        cast(Any, fake),
        cast(
            Any, SimpleNamespace(asset_channel_id=None, asset_guild_id=888)
        ),
        str(tmp_path),
    )
    await assets.reconcile()
    await assets.sync_cdn(cast(Any, None))

    # one pause between the two creates, of the configured delay
    assert slept == [_EMOJI_CREATE_DELAY]


async def test_reconcile_kind_change_republishes_as_emoji(
    asset_db: Database, tmp_path: Path
) -> None:
    """Re-declaring an asset as EMOJI re-queues it and re-publishes as one.

    Regression for the reported flow: changing ``AssetKind.SPECIES`` →
    ``AssetKind.EMOJI`` on the same enum member (same key, unchanged file)
    must update the stored kind and reset ``url`` so ``sync_cdn`` creates a
    guild emoji instead of re-uploading to the channel as media.
    """
    _write_glyph(tmp_path, "glyph.png", b"same bytes every time")
    # same enum class name + member ⇒ same derived key, only the kind differs
    _SpeciesGlyph = Enum(
        "_GlyphAsset",
        {
            "GLYPH": AssetSpec(
                kind=AssetKind.SPECIES, path="assets/glyph.png"
            )
        },
    )
    _EmojiGlyph = Enum(
        "_GlyphAsset",
        {
            "GLYPH": AssetSpec(
                kind=AssetKind.EMOJI, path="assets/glyph.png"
            )
        },
    )

    plugin = _EmojiPlugin()  # name="emojis" → file under emojis/assets/
    plugin.asset_decl = _SpeciesGlyph
    fake = _FakeBot(asset_db, str(tmp_path))
    fake.plugins = [plugin]

    async def _create_emoji(guild_id: int, **_: object) -> _FakeEmoji:
        return _FakeEmoji(4242)

    async def _create_message(channel_id: int, **_: object) -> FakeMessage:
        message = FakeMessage(id=1, channel_id=channel_id)
        message.attachments = [
            FakeAttachment(
                id=1, filename="glyph.png", url=_url(777, 1, "glyph.png")
            )
        ]
        return message

    cast(Any, fake).rest = SimpleNamespace(
        create_emoji=_create_emoji,
        create_message=_create_message,
        delete_message=lambda c, m: None,
    )
    assets = Assets(
        cast(Any, fake),
        cast(
            Any, SimpleNamespace(asset_channel_id=777, asset_guild_id=888)
        ),
        str(tmp_path),
    )

    # first pass: registered as SPECIES media and published as a CDN url
    await assets.reconcile()
    await assets.sync_cdn(cast(Any, None))
    key = asset_key(_SpeciesGlyph.GLYPH)
    row = await asset_db.fetchone(
        "SELECT kind, url FROM asset WHERE key = ?", key
    )
    assert row is not None
    assert row["kind"] == "species"
    assert row["url"] is not None  # published as media

    # re-declare the same key as EMOJI — file bytes unchanged
    plugin.asset_decl = _EmojiGlyph
    await assets.reconcile()
    row = await asset_db.fetchone(
        "SELECT kind, sha256, url FROM asset WHERE key = ?", key
    )
    assert row is not None
    assert row["kind"] == "emoji"  # declaration kind won
    assert row["url"] is None  # re-queued

    await assets.sync_cdn(cast(Any, None))
    assert await assets.get(_EmojiGlyph.GLYPH) == f"<:glyph:{4242}>"
