"""Core asset management — typed declarations, derived keys, CDN sync.

Static path only (the dynamic admin-upload path from docs/ASSETS.md stays
deferred): a plugin declares its assets as an **enum** — each member's
value is an :class:`AssetSpec` (kind + file relative to the plugin folder)
and the member itself IS the reference to the asset. The registry key is
*derived* from the enum identity (``asset_key``) — never hand-written —
and code references assets by member only (``bot.assets.get(member)``).

Because the declaration enum IS the reference set, "referenced but
undeclared" cannot be spelled: an asset's existence is a type-level
guarantee, and reconcile only verifies the real runtime facts (the file
exists on disk; its content hash matches).

Failure policy mirrors ``Database.verify_schema``: a missing declared file
aborts boot (the caller decides how to fail). ``sync_cdn`` is skipped with
a boot warning when no asset channel is configured.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import hikari

from cazzubot.config import Config

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

_SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS asset (
		key    TEXT PRIMARY KEY,
		kind   TEXT NOT NULL,
		sha256 TEXT NOT NULL,
		path   TEXT NOT NULL,
		url    TEXT
	)
	""",
]

# Public alias for tooling that needs the DDL without instantiating the class.
SCHEMA = _SCHEMA


class AssetError(RuntimeError):
    """Boot-aborting asset drift: a declared file is missing."""


class AssetKind(Enum):
    """The asset category — declared and stored, but not yet consumed.

    Typed, self-documenting declaration metadata: it records what each
    declared asset *is* (species art vs. badge art vs. dish art) in the
    registry's ``kind`` column, so the category cannot drift into a magic
    string. Nothing reads the column back today — its purpose right now
    is internal documentation. A future kind-driven feature (cataloging
    only species art, badge/dish/shop assets) is where it earns its keep;
    that future may also nest the members (e.g. ``AssetKind.SPECIES`` →
    species-scoped members) for a better workflow instead of the current
    flat single member.
    """

    SPECIES = "species"


@dataclass(frozen=True, slots=True)
class AssetSpec:
    """The declaration payload carried by one asset enum member.

    The member's enum identity supplies the registry key (see
    :func:`asset_key`); this struct supplies the rest.
    """

    kind: AssetKind
    path: str  # file relative to the owning plugin's folder


def asset_key(asset: Enum) -> str:
    """The registry key for an asset — derived, never hand-written.

    ``"<EnumClass>.<MEMBER>"`` — unique across plugins by enum name and
    stable under plugin/renames of the underlying files.
    """
    return f"{type(asset).__name__}.{asset.name}"


class Assets:
    """Owns the registry table, boot reconcile and CDN sync.

    Mirrors ``Settings``/``Scheduler``: a core service on ``CazzuBot``
    (``bot.assets``) whose schema runs at boot and whose sync rides the
    ``StartedEvent`` ready gate (REST is up then — same reasoning as the
    scheduler).
    """

    def __init__(
        self, bot: "CazzuBot", config: Config, plugins_dir: str
    ) -> None:
        self.bot = bot
        self.config = config
        self.plugins_dir = Path(plugins_dir)
        self.bot.subscribe(hikari.StartedEvent, self.sync_cdn)

    @property
    def schema(self) -> list[str]:
        return _SCHEMA

    # -- boot reconcile -----------------------------------------------------

    async def reconcile(self) -> None:
        """Hash declared assets, upsert registry rows, abort on drift.

        Walks every plugin's ``asset_decl`` enum — the members ARE the
        declarations, so the registry can only contain spelled references.
        The file on disk is the source of truth: a row is inserted when
        missing, its hash (and URL) refreshed when the file changed. A
        missing file raises :class:`AssetError` — the caller decides how
        to fail (boot abort, mirroring ``Database.verify_schema``).
        """
        for plugin in self.bot.plugins:
            decl = plugin.asset_decl
            if decl is None:
                continue
            for asset in decl:
                spec = asset.value
                key = asset_key(asset)
                path = self.plugins_dir / plugin.name / spec.path
                if not path.is_file():
                    raise AssetError(
                        f"asset {key!r} ({plugin.name}) file missing: "
                        f"{path}"
                    )
                sha = _sha256(path)
                row = await self.bot.db.fetchone(
                    "SELECT sha256 FROM asset WHERE key = ?", key
                )
                if row is None:
                    await self.bot.db.execute(
                        """
						INSERT INTO asset (key, kind, sha256, path)
						VALUES (?, ?, ?, ?)
						""",
                        key,
                        spec.kind.value,
                        sha,
                        f"{plugin.name}/{spec.path}",
                    )
                    _log.info("asset %s registered (%s)", key, sha[:8])
                elif row["sha256"] != sha:
                    # changed on disk — re-publish on the next CDN sync
                    await self.bot.db.execute(
                        "UPDATE asset SET sha256 = ?, url = NULL WHERE key = ?",
                        sha,
                        key,
                    )
                    _log.info("asset %s changed; re-queuing CDN sync", key)

    # -- CDN sync -----------------------------------------------------------

    async def sync_cdn(self, _event: hikari.StartedEvent) -> None:
        """Upload new/changed blobs to the asset channel, store the URLs.

        Only rows with a NULL ``url`` (new or hash-changed) upload — the
        sha256 diff keeps re-uploads to content changes only. Skipped with
        a boot warning when no asset channel is configured (the bot keeps
        running; ``get`` returns None for unpublished assets).
        """
        channel_id = self.config.asset_channel_id
        if channel_id is None:
            _log.warning(
                "no asset channel configured (ASSET_CHANNEL_PROD/DEV); "
                "skipping CDN sync"
            )
            return
        rows = await self.bot.db.fetchall(
            "SELECT * FROM asset WHERE url IS NULL"
        )
        for row in rows:
            path = self.plugins_dir / row["path"]
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                _log.error(
                    "asset %s file missing at sync time: %s",
                    row["key"],
                    path,
                )
                continue
            message = await self.bot.rest.create_message(
                channel_id, attachment=hikari.Bytes(data, path.name)
            )
            url = message.attachments[0].url
            await self.bot.db.execute(
                "UPDATE asset SET url = ? WHERE key = ?", url, row["key"]
            )
            _log.info("asset %s published (%s)", row["key"], url)

    # -- runtime lookup -----------------------------------------------------

    async def get(self, asset: Enum) -> str | None:
        """The published CDN URL for a declared asset member.

        ``None`` when the asset isn't published yet (no channel configured
        or a pending re-sync). Raises ``KeyError`` for an unknown asset —
        a programming error that is structurally impossible for members of
        a loaded plugin's declaration enum.
        """
        key = asset_key(asset)
        row = await self.bot.db.fetchone(
            "SELECT url FROM asset WHERE key = ?", key
        )
        if row is None:
            raise KeyError(f"unknown asset key {key!r}")
        return row["url"]


def _sha256(path: Path) -> str:
    """Content address of a file (the registry's drift signal)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()
