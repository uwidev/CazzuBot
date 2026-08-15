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
exists on disk; its content hash matches). The registry is a **projection
of the declarations**: rows whose key is no longer declared are pruned
(their CDN message deleted), and every published URL is re-verified on
boot — a deleted CDN message re-queues its row for re-publish.

Failure policy mirrors ``Database.verify_schema``: a missing declared file
aborts boot (the caller decides how to fail). ``sync_cdn`` is skipped with
a boot warning when no asset channel is configured.
"""

from __future__ import annotations

import hashlib
import logging
import re
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
        # CDN message URLs queued for deletion by the last reconcile's
        # prune — the sync performs the REST deletes (REST is up by then).
        self._pending_message_deletes: list[str] = []
        self.bot.subscribe(hikari.StartedEvent, self.sync_cdn)

    @property
    def schema(self) -> list[str]:
        return _SCHEMA

    # -- boot reconcile -----------------------------------------------------

    async def reconcile(self) -> None:
        """Hash declared assets, upsert registry rows, prune the stale.

        Walks every plugin's ``asset_decl`` enum — the members ARE the
        declarations, so the registry can only contain spelled references.
        The file on disk is the source of truth: a row is inserted when
        missing, its hash (and URL) refreshed when the file changed. A
        missing file raises :class:`AssetError` — the caller decides how
        to fail (boot abort, mirroring ``Database.verify_schema``).

        The registry is a **projection of the declarations**: after the
        walk, rows whose key no loaded plugin declares are stale (an
        asset definition deleted from code) and are pruned — their row is
        dropped and their published CDN message (if any) is queued for
        deletion on the next ``sync_cdn``.
        """
        declared: set[str] = set()
        for plugin in self.bot.plugins:
            decl = plugin.asset_decl
            if decl is None:
                continue
            for asset in decl:
                spec = asset.value
                key = asset_key(asset)
                declared.add(key)
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
        await self._prune_undeclared(declared)

    async def _prune_undeclared(self, declared: set[str]) -> None:
        """Drop registry rows for assets no longer declared (if any).

        A key that no loaded plugin declares anymore is stale — the
        definition was deleted from code, so the row (and its published
        CDN message, queued via :attr:`_pending_message_deletes`) must
        go. Re-declaring the asset re-registers and re-publishes it on
        the next boot: the prune is fully idempotent.
        """
        rows = await self.bot.db.fetchall("SELECT key, url FROM asset")
        for row in rows:
            if row["key"] in declared:
                continue
            if row["url"]:
                self._pending_message_deletes.append(row["url"])
            await self.bot.db.execute(
                "DELETE FROM asset WHERE key = ?", row["key"]
            )
            _log.info("pruned undeclared asset %s", row["key"])

    # -- CDN sync -----------------------------------------------------------

    async def sync_cdn(self, _event: hikari.StartedEvent) -> None:
        """Publish, verify and prune the asset channel.

        Runs on every boot (the ``StartedEvent`` ready gate). Three
        passes:

        1. **Verify** — every published row's CDN message is fetched; a
           deleted message (accidental or otherwise) resets the row's
           ``url`` so it re-publishes below. The registry never serves a
           dead URL.
        2. **Cleanup** — CDN messages queued by the last reconcile's
           prune (assets deleted from code) are deleted best-effort.
        3. **Upload** — only rows with a NULL ``url`` (new or
           hash-changed or just re-verified-dead) upload; the sha256
           diff keeps re-uploads to content changes only.

        Skipped with a boot warning when no asset channel is configured
        (the bot keeps running; ``get`` returns None for unpublished
        assets).
        """
        channel_id = self.config.asset_channel_id
        if channel_id is None:
            _log.warning(
                "no asset channel configured (ASSET_CHANNEL_PROD/DEV); "
                "skipping CDN sync"
            )
            return
        await self._verify_published(channel_id)
        await self._delete_orphaned_messages(channel_id)
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

    async def _verify_published(self, channel_id: int) -> None:
        """Re-check published URLs — a deleted CDN message re-queues the row.

        A Discord CDN URL embeds its message id, so liveness is one
        ``fetch_message`` per published asset. Only a definitive
        ``NotFoundError`` (the message is gone) resets the row; any other
        failure (permissions, transient) logs and leaves the URL alone —
        a hiccup must not cause a re-upload storm.
        """
        rows = await self.bot.db.fetchall(
            "SELECT key, url FROM asset WHERE url IS NOT NULL"
        )
        for row in rows:
            message_id = _message_id(row["url"])
            if message_id is None:
                _log.warning(
                    "asset %s has an unparseable URL: %s",
                    row["key"],
                    row["url"],
                )
                continue
            try:
                await self.bot.rest.fetch_message(channel_id, message_id)
            except hikari.NotFoundError:
                _log.info(
                    "asset %s CDN message gone; re-queuing publish",
                    row["key"],
                )
                await self.bot.db.execute(
                    "UPDATE asset SET url = NULL WHERE key = ?", row["key"]
                )
            except Exception:
                _log.exception(
                    "failed to verify asset %s publication", row["key"]
                )

    async def _delete_orphaned_messages(self, channel_id: int) -> None:
        """Best-effort deletion of CDN messages for pruned assets.

        Consumes and clears :attr:`_pending_message_deletes` (queued by
        reconcile's prune). A message that is already gone is fine; other
        failures are logged and the cleanup is retried next boot (the
        prune re-queues the URL then).
        """
        pending, self._pending_message_deletes = (
            self._pending_message_deletes,
            [],
        )
        for url in pending:
            message_id = _message_id(url)
            if message_id is None:
                continue
            try:
                await self.bot.rest.delete_message(channel_id, message_id)
            except hikari.NotFoundError:
                pass  # already gone
            except Exception:
                _log.exception(
                    "failed to delete orphaned asset message %s", url
                )

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


_ATTACHMENT_URL = re.compile(r"/attachments/\d+/(\d+)/")


def _message_id(url: str) -> int | None:
    """The Discord message id embedded in a CDN attachment URL.

    CDN URLs look like ``…/attachments/<channel>/<message>/<file>``; the
    message id is how the sync finds (and deletes) the published message.
    Returns None when the URL isn't a recognizable attachment URL.
    """
    match = _ATTACHMENT_URL.search(url)
    return int(match.group(1)) if match else None
