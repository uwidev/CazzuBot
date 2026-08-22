"""Core asset management — typed declarations, derived keys, kind-based sync.

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
(their published reference removed), and every published reference is
re-verified on boot — a dead one re-queues its row for re-publish.

The kind dispatches the sync to the shared **asset child-guild**: media
(``SPECIES``) blobs CDN-publish into a private channel, while ``EMOJI``
assets are created as custom emoji in the guild and referenced as
``<:name:id>`` — both stored in the row's ``url``.

Failure policy mirrors ``Database.verify_schema``: a missing declared file
aborts boot (the caller decides how to fail). ``sync_cdn`` is skipped with
a boot warning when neither the asset guild nor channel is configured.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import hikari

from cazzubot.config import Config
from cazzubot.db import rows_to

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

# Discord limits: a guild emoji image must be ≤256 KB, and emoji creation is
# rate-limited (~5 per 10 s). The delay paces a batch of creates below that.
_MAX_EMOJI_BYTES = 256 * 1024
_EMOJI_CREATE_DELAY = 2.0

# A custom-emoji reference as stored in a row's ``url``: <:name:id> (static)
# or <a:name:id> (animated). The ``id`` is what emoji CRUD needs.
_EMOJI_REF = re.compile(r"^<(a)?:([\w]+):(\d+)>$")

_ATTACHMENT_URL = re.compile(r"/attachments/\d+/(\d+)/")


class AssetError(RuntimeError):
    """Boot-aborting asset drift: a declared file is missing."""


class AssetKind(Enum):
    """The asset category — declared, stored, and consumed by the sync.

    It records what each declared asset *is* (species art vs. badge art vs.
    dish art vs. an inline emoji glyph) in the registry's ``kind`` column,
    so the category cannot drift into a magic string. The kind is what the
    sync dispatches on: ``SPECIES``/media blobs CDN-publish into the asset
    channel, while ``EMOJI`` assets are created as custom emoji in the asset
    guild and referenced as ``<:name:id>`` (both stored in the row's ``url``
    — ``get()`` returns whichever reference applies). A future kind-driven
    feature (cataloging only species art, badge/dish/shop assets) is where
    it earns its keep; that future may also nest the members (e.g.
    ``AssetKind.SPECIES`` → species-scoped members) for a better workflow
    instead of the current flat single member.
    """

    SPECIES = "species"
    EMOJI = "emoji"


@dataclass(frozen=True, slots=True)
class AssetSpec:
    """The declaration payload carried by one asset enum member.

    The member's enum identity supplies the registry key (see
    :func:`asset_key`); this struct supplies the rest.
    """

    kind: AssetKind
    path: str  # file relative to the owning plugin's folder


@dataclass(frozen=True, slots=True)
class AssetRow:
    """One ``asset`` registry row (``url`` is None until published)."""

    key: str
    kind: AssetKind
    sha256: str
    path: str
    url: str | None


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
        """Bind the bot service and set the plugin assets root.

        Subscribes ``self.sync_cdn`` to the ``StartedEvent`` ready gate so
        CDN publishing runs only once REST is up.
        """
        self.bot = bot
        self.config = config
        self.plugins_dir = Path(plugins_dir)
        # Stored references queued for deletion by the last reconcile's
        # prune or an emoji/media hash-change — the sync performs the REST
        # deletes (REST is up by then). Each entry is a row's ``url``: a CDN
        # message URL for media, a ``<:name:id>`` emoji reference for emoji.
        self._pending_deletes: list[str] = []
        # Throttle pacing: count emoji creates within one sync pass so we
        # sleep *between* consecutive creates (never before the first).
        self._emoji_created_this_pass = 0
        self.bot.subscribe(hikari.StartedEvent, self.sync_cdn)

    schema = _SCHEMA

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
                stored_path = f"{plugin.name}/{spec.path}"
                row = await self.bot.db.fetch_model(
                    AssetRow,
                    "SELECT key, sha256, url, kind, path FROM asset WHERE key = ?",
                    key,
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
                        stored_path,
                    )
                    _log.info("asset %s registered (%s)", key, sha[:8])
                elif (
                    row.sha256 != sha
                    # the declaration is the source of truth — a change of
                    # kind (SPECIES → EMOJI) or path on an unchanged file
                    # must re-publish under the new kind, not silently keep
                    # the stale row
                    or row.kind is not spec.kind
                    or row.path != stored_path
                ):
                    # changed (bytes, kind, or path) — re-publish on the next
                    # CDN sync. The old published ref (media CDN URL or emoji
                    # <:name:id>) is queued for deletion (an emoji's image is
                    # immutable, so a changed emoji file means delete + recreate).
                    if row.url:
                        self._pending_deletes.append(row.url)
                    await self.bot.db.execute(
                        """
						UPDATE asset
						SET sha256 = ?, kind = ?, path = ?, url = NULL
						WHERE key = ?
						""",
                        sha,
                        spec.kind.value,
                        stored_path,
                        key,
                    )
                    _log.info("asset %s changed; re-queuing sync", key)
        await self._prune_undeclared(declared)

    async def _prune_undeclared(self, declared: set[str]) -> None:
        """Drop registry rows for assets no longer declared (if any).

        A key that no loaded plugin declares anymore is stale — the
        definition was deleted from code, so the row (and its published
        reference: a CDN message for media, a guild emoji for emoji, both
        queued via :attr:`_pending_deletes`) must go. Re-declaring the asset
        re-registers and re-publishes it on the next boot: the prune is
        fully idempotent.
        """
        rows = await self.bot.db.fetchall(
            "SELECT key, kind, sha256, path, url FROM asset"
        )
        for row in rows_to(AssetRow, rows):
            if row.key in declared:
                continue
            if row.url:
                self._pending_deletes.append(row.url)
            await self.bot.db.execute(
                "DELETE FROM asset WHERE key = ?", row.key
            )
            _log.info("pruned undeclared asset %s", row.key)

    # -- sync ---------------------------------------------------------------

    async def sync_cdn(self, _event: hikari.StartedEvent) -> None:
        """Publish, verify and prune the asset child-guild.

        Runs on every boot (the ``StartedEvent`` ready gate). Three
        passes over the shared asset child-guild (``ASSET_GUILD_ID`` /
        ``ASSET_CHANNEL_ID``):

        1. **Verify** — every published media row's CDN message (and every
           emoji row's guild emoji) is fetched; a deleted one (accidental
           or otherwise) resets the row's ``url`` so it re-publishes
           below. The registry never serves a dead reference.
        2. **Cleanup** — stored references queued by the last reconcile's
           prune or a hash-change (deleted assets) are removed
           best-effort: CDN messages for media, guild emojis for emoji.
        3. **Publish** — only rows with a NULL ``url`` (new, hash-changed
           or just re-verified-dead) publish: media uploads into the asset
           channel; emoji assets are created as custom emoji in the asset
           guild. The sha256 diff keeps re-publishes to content changes
           only.

        Skipped with a boot warning when neither the asset channel nor the
        asset guild is configured (the bot keeps running; ``get`` returns
        None for unpublished assets).
        """
        channel_id = self.config.asset_channel_id
        guild_id = getattr(self.config, "asset_guild_id", None)
        if channel_id is None and guild_id is None:
            _log.warning(
                "no asset channel/guild configured; skipping asset sync"
            )
            return
        self._emoji_created_this_pass = 0
        await self._verify_published(channel_id, guild_id)
        await self._delete_orphaned(channel_id, guild_id)
        rows = await self.bot.db.fetchall(
            "SELECT key, kind, sha256, path, url FROM asset WHERE url IS NULL"
        )
        for row in rows_to(AssetRow, rows):
            if row.kind is AssetKind.EMOJI:
                if guild_id is None:
                    _log.warning(
                        "asset %s is emoji but ASSET_GUILD_ID unset; skipping",
                        row.key,
                    )
                    continue
                await self._publish_emoji(guild_id, row)
                continue
            if channel_id is None:
                _log.warning(
                    "asset %s is media but ASSET_CHANNEL_ID unset; skipping",
                    row.key,
                )
                continue
            path = self.plugins_dir / row.path
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                _log.error(
                    "asset %s file missing at sync time: %s",
                    row.key,
                    path,
                )
                continue
            message = await self.bot.rest.create_message(
                channel_id, attachment=hikari.Bytes(data, path.name)
            )
            url = message.attachments[0].url
            await self.bot.db.execute(
                "UPDATE asset SET url = ? WHERE key = ?", url, row.key
            )
            _log.info("asset %s published (%s)", row.key, url)

    async def _publish_emoji(self, guild_id: int, row: AssetRow) -> None:
        """Create a guild emoji for an emoji-kind asset, store ``<:name:id>``.

        Emoji images are immutable and capped at 256 KB, so an over-large
        or unreadable file is skipped (logged) rather than created. Creates
        are paced to Discord's rate limit: sleep *between* consecutive
        creates within a sync pass, never before the first.
        """
        path = self.plugins_dir / row.path
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            _log.error(
                "asset %s file missing at sync time: %s", row.key, path
            )
            return
        if len(data) > _MAX_EMOJI_BYTES:
            _log.error(
                "asset %s file too large for a guild emoji (%d bytes)",
                row.key,
                len(data),
            )
            return
        name = _emoji_name_from_key(row.key)
        emoji = await self.bot.rest.create_emoji(
            guild_id,
            name=name,
            image=hikari.Bytes(data, path.name),
        )
        ref = f"<:{name}:{emoji.id}>"
        await self.bot.db.execute(
            "UPDATE asset SET url = ? WHERE key = ?", ref, row.key
        )
        _log.info("asset %s published as emoji (%s)", row.key, ref)
        self._emoji_created_this_pass += 1
        if self._emoji_created_this_pass > 1:
            await asyncio.sleep(_EMOJI_CREATE_DELAY)

    async def _verify_published(
        self, channel_id: int | None, guild_id: int | None
    ) -> None:
        """Re-check published references — a dead one re-queues the row.

        Media rows are liveness-checked with one ``fetch_message`` (a CDN
        URL embeds its message id); emoji rows with one ``fetch_guild_emoji``.
        Only a definitive ``NotFoundError`` resets the row; any other
        failure (permissions, transient) logs and leaves the reference
        alone — a hiccup must not cause a re-publish storm.
        """
        rows = await self.bot.db.fetchall(
            "SELECT key, kind, sha256, path, url FROM asset WHERE url IS NOT NULL"
        )
        for row in rows_to(AssetRow, rows):
            if row.url is None:
                continue  # the query excludes NULLs; defensive narrowing
            if row.kind is AssetKind.EMOJI:
                if guild_id is None:
                    _log.warning(
                        "asset %s is emoji but ASSET_GUILD_ID unset; "
                        + "skipping verification",
                        row.key,
                    )
                    continue
                emoji_id = _emoji_id_from_ref(row.url)
                if emoji_id is None:
                    _log.warning(
                        "asset %s has an unparseable emoji ref: %s",
                        row.key,
                        row.url,
                    )
                    continue
                try:
                    await self.bot.rest.fetch_emoji(guild_id, emoji_id)
                except hikari.NotFoundError:
                    _log.info(
                        "asset %s emoji gone; re-queuing publish",
                        row.key,
                    )
                    await self.bot.db.execute(
                        "UPDATE asset SET url = NULL WHERE key = ?",
                        row.key,
                    )
                except Exception:
                    _log.exception(
                        "failed to verify asset %s emoji", row.key
                    )
                continue
            if channel_id is None:
                _log.warning(
                    "asset %s is media but ASSET_CHANNEL_ID unset; "
                    + "skipping verification",
                    row.key,
                )
                continue
            message_id = _message_id(row.url)
            if message_id is None:
                _log.warning(
                    "asset %s has an unparseable URL: %s",
                    row.key,
                    row.url,
                )
                continue
            try:
                await self.bot.rest.fetch_message(channel_id, message_id)
            except hikari.NotFoundError:
                _log.info(
                    "asset %s CDN message gone; re-queuing publish",
                    row.key,
                )
                await self.bot.db.execute(
                    "UPDATE asset SET url = NULL WHERE key = ?", row.key
                )
            except Exception:
                _log.exception(
                    "failed to verify asset %s publication", row.key
                )

    async def _delete_orphaned(
        self, channel_id: int | None, guild_id: int | None
    ) -> None:
        """Best-effort removal of stored references for pruned assets.

        Consumes and clears :attr:`_pending_deletes` (queued by reconcile's
        prune and emoji/media hash-changes). Each reference is deleted by
        kind: emoji ``<:name:id>`` → ``delete_guild_emoji``, CDN URL →
        ``delete_message``. A reference that is already gone is fine; other
        failures are logged and the cleanup is retried next boot (the prune
        re-queues it then).
        """
        pending, self._pending_deletes = self._pending_deletes, []
        for ref in pending:
            if _is_emoji_ref(ref):
                emoji_id = _emoji_id_from_ref(ref)
                if guild_id is None or emoji_id is None:
                    continue
                try:
                    await self.bot.rest.delete_emoji(guild_id, emoji_id)
                except hikari.NotFoundError:
                    pass  # already gone
                except Exception:
                    _log.exception(
                        "failed to delete orphaned emoji %s", ref
                    )
                continue
            if channel_id is None:
                continue
            message_id = _message_id(ref)
            if message_id is None:
                continue
            try:
                await self.bot.rest.delete_message(channel_id, message_id)
            except hikari.NotFoundError:
                pass  # already gone
            except Exception:
                _log.exception(
                    "failed to delete orphaned asset message %s", ref
                )

    # -- runtime lookup -----------------------------------------------------

    async def get(self, asset: Enum) -> str | None:
        """The published reference for a declared asset member.

        The stored reference — a CDN URL for media (``SPECIES``) or a
        ``<:name:id>`` string for an inline emoji (``EMOJI``). ``None``
        when the asset isn't published yet (no asset guild/channel
        configured or a pending re-sync). Raises ``KeyError`` for an
        unknown asset — a programming error that is structurally
        impossible for members of a loaded plugin's declaration enum.
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


def _message_id(url: str) -> int | None:
    """The Discord message id embedded in a CDN attachment URL.

    CDN URLs look like ``…/attachments/<channel>/<message>/<file>``; the
    message id is how the sync finds (and deletes) the published message.
    Returns None when the URL isn't a recognizable attachment URL.
    """
    match = _ATTACHMENT_URL.search(url)
    return int(match.group(1)) if match else None


def _is_emoji_ref(ref: str) -> bool:
    """Whether a stored reference is a custom-emoji ``<:name:id>`` (or
    ``<a:name:id>``) rather than a CDN URL."""
    return _EMOJI_REF.match(ref) is not None


def _emoji_id_from_ref(ref: str) -> int | None:
    """The numeric id hidden inside a ``<:name:id>`` emoji reference."""
    match = _EMOJI_REF.match(ref)
    return int(match.group(3)) if match else None


def _emoji_name_from_key(asset_key: str) -> str:
    """Derive a valid Discord emoji name from an asset key.

    Discord emoji names are 2–32 chars of lower-case alphanumerics and
    underscores, not starting/ending with ``_``. Derived from the stable
    asset key (``EnumClass.MEMBER``) so it never collides and stays stable
    across boots, rather than a hand-written literal.
    """
    name = asset_key.split(".")[-1].lower()
    name = re.sub(r"[^a-z0-9_]", "", name).strip("_")
    return name[:32]
