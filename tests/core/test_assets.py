"""Asset core — typed declarations, derived keys, reconcile, CDN sync."""

from __future__ import annotations

import hashlib
import logging
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from cazzubot import AssetKind, AssetSpec, Assets, Plugin
from cazzubot.assets import SCHEMA, AssetError, asset_key
from cazzubot.db import Database
from tests.fakes import FakeAttachment, FakeMessage


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
    channel_id: int | None,
) -> Assets:
    fake = _FakeBot(db, plugins_dir)
    fake.plugins = [_AssetsPlugin()]
    config = SimpleNamespace(asset_channel_id=channel_id)
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
        "no asset channel configured" in record.message
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
