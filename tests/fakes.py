# pyright: reportAttributeAccessIssue=false
"""Typed fakes for hikari objects, used across the test suite.

Standalone classes — hikari models are immutable ``attrs`` objects with
``__slots__``, so the old discord.py "subclass without ``super().__init__``"
trick is impossible. The surface below is the HIKARI_MIGRATION.md freeze
list: member identity (``id``/``display_name``/``mention``/``avatar_url``),
role ids + permissions, rest-client spies for mutations, cache-backed
lookups, and a lightbulb-style command context whose ``respond`` records
sends.

Anything a ported extension calls that we forgot to fake raises ``AttributeError``
loudly at the test — a feature, not a bug: the traceback names the exact
attribute to add.

Pure-data hikari classes (``hikari.Embed``, ``hikari.Permissions``) are NOT
faked here — they construct fine offline.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import hikari

from cazzubot import utils


class InstantAsyncio:
    """An ``asyncio`` stand-in whose ``sleep`` never waits.

    Tests patch ``plugins.frogs.behaviors.asyncio`` with this so the
    cluster burst's 0.75s inter-child rate-limit guard doesn't burn real
    clock; ``create_task`` delegates to the real loop so the tracked
    background children still run. Never patch the global ``asyncio`` —
    the driver harness polls on the real ``asyncio.sleep``.
    """

    async def sleep(self, _seconds: float) -> None:
        """No-op: the guard's timing is not what the burst tests assert."""

    def create_task(
        self, coro: Any, *, name: str | None = None
    ) -> Any:
        import asyncio

        return asyncio.create_task(coro, name=name)


def _avatar_url(uid: int) -> str:
    return f"https://example.com/avatar/{uid}.png"


# -- User / Member --------------------------------------------------------


class FakeUser:
    """Minimal hikari-style user (Member subclasses it, like hikari)."""

    def __init__(
        self,
        *,
        id: int,
        name: str,
        bot: bool = False,
        global_name: str | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.bot = bot
        self.global_name = global_name

    def __str__(self) -> str:
        return self.name

    @property
    def display_name(self) -> str:
        return self.global_name or self.name

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    @property
    def avatar_url(self) -> str:
        return _avatar_url(self.id)

    @property
    def display_avatar_url(self) -> str:
        return _avatar_url(self.id)


class FakeMember(FakeUser):
    """Guild member: role ids + permissions, mutation goes via FakeRest."""

    def __init__(
        self,
        *,
        id: int,
        name: str,
        guild: FakeGuild | None = None,
        roles: list[FakeRole] | None = None,
        administrator: bool = False,
        bot: bool = False,
    ) -> None:
        super().__init__(id=id, name=name, bot=bot)
        self.guild_id: int | None = guild.id if guild is not None else None
        self.nickname: str | None = None
        self.role_ids: set[int] = {r.id for r in (roles or [])}
        self.permissions: hikari.Permissions = (
            hikari.Permissions(hikari.Permissions.ADMINISTRATOR)
            if administrator
            else hikari.Permissions.NONE
        )
        self.joined_at: datetime | None = None
        self.is_pending: bool = False

    @property
    def display_name(self) -> str:
        return self.nickname or self.global_name or self.name


# -- Role / Guild / Channel / Message --------------------------------------


class FakeRole:
    def __init__(
        self,
        *,
        id: int,
        name: str,
        permissions: hikari.Permissions | None = None,
        position: int = 0,
    ) -> None:
        self.id = id
        self.name = name
        self.permissions = permissions or hikari.Permissions.NONE
        self.position = position

    @property
    def mention(self) -> str:
        return f"<@&{self.id}>"


class FakeGuild:
    def __init__(
        self,
        *,
        id: int = 2,
        name: str = "Test Guild",
        owner_id: int = 1,
    ) -> None:
        self.id = id
        self.name = name
        self.owner_id = owner_id
        self.channels: dict[int, FakeChannel] = {}

    def get_channels(self) -> dict[int, FakeChannel]:
        return self.channels


class FakeChannel:
    def __init__(
        self,
        *,
        id: int,
        name: str = "general",
        guild_id: int | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.guild_id = guild_id
        self.position: int = 0
        self.type: hikari.ChannelType | None = (
            hikari.ChannelType.GUILD_TEXT
        )
        self.sent: list[dict[str, Any]] = []
        self.messages: list[FakeMessage] = []

    @property
    def mention(self) -> str:
        return f"<#{self.id}>"

    async def send(
        self, content: str | None = None, **kwargs: Any
    ) -> FakeMessage:
        self.sent.append({"content": content, **kwargs})
        message = FakeMessage(
            id=len(self.messages) + 1,
            content=content or "",
            guild_id=self.guild_id,
            channel_id=self.id,
        )
        self.messages.append(message)
        return message


class FakeAttachment:
    """hikari.Attachment stand-in for the board/misc scrapers."""

    def __init__(
        self,
        *,
        id: int = 1,
        filename: str = "a.png",
        url: str = "https://example.com/a.png",
        media_type: str = "image/png",
    ) -> None:
        self.id = id
        self.filename = filename
        self.url = url
        self.media_type = media_type


class FakeMessage:
    def __init__(
        self,
        *,
        id: int = 1,
        content: str = "",
        author: FakeMember | FakeUser | None = None,
        guild_id: int | None = None,
        channel_id: int | None = None,
        created_at: datetime | None = None,
        embeds: list[hikari.Embed] | None = None,
        attachments: list[FakeAttachment] | None = None,
    ) -> None:
        self.id = id
        self.content = content
        self.author = author
        self.member: FakeMember | None = (
            author if isinstance(author, FakeMember) else None
        )
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.created_at = created_at or datetime.now(timezone.utc)
        self.embeds = embeds or []
        self.attachments: list[FakeAttachment] = attachments or []
        self.components: list[Any] = []
        # kwargs the FakeRest.create_message call was made with (for tests
        # to assert e.g. user_mentions/role_mentions on the board post)
        self.create_kwargs: dict[str, Any] | None = None


# -- Cache / Rest ----------------------------------------------------------


def _not_found(message: str) -> hikari.NotFoundError:
    """A raise-ready NotFoundError with minimal payload."""
    headers: dict[str, str] = {}
    return hikari.NotFoundError(
        url="https://example.com",
        headers=headers,
        raw_body=None,
        message=message,
    )


class FakeCache:
    """Stand-in for hikari's CacheImpl: plain dicts, seedable by hand."""

    def __init__(self) -> None:
        self._guilds: dict[int, FakeGuild] = {}
        self._members: dict[tuple[int, int], FakeMember] = {}
        self._users: dict[int, FakeUser] = {}
        self._roles: dict[int, FakeRole] = {}
        self._channels: dict[int, FakeChannel] = {}

    def get_guild(self, guild_id: int) -> FakeGuild | None:
        return self._guilds.get(guild_id)

    def get_member(self, guild_id: int, user_id: int) -> FakeMember | None:
        return self._members.get((guild_id, user_id))

    def get_user(self, user_id: int) -> FakeUser | None:
        return self._users.get(user_id)

    def get_role(self, role_id: int) -> FakeRole | None:
        return self._roles.get(role_id)

    def get_guild_channel(self, channel_id: int) -> FakeChannel | None:
        return self._channels.get(channel_id)

    def add_guild(self, guild: FakeGuild) -> None:
        self._guilds[guild.id] = guild

    def add_member(self, member: FakeMember) -> None:
        if member.guild_id is not None:
            self._members[(member.guild_id, member.id)] = member
        self._users[member.id] = member

    def add_role(self, role: FakeRole) -> None:
        self._roles[role.id] = role

    def add_channel(self, channel: FakeChannel) -> None:
        self._channels[channel.id] = channel


class FakeRest:
    """Rest-client spy: records mutations, serves cache-backed fetches.

    Mirrors the hikari REST surface the presenters use — member mutations
    live here (not on the member), per the HIKARI_MIGRATION.md freeze list.
    """

    def __init__(self) -> None:
        self.guilds: dict[int, FakeGuild] = {}
        self.members: dict[tuple[int, int], FakeMember] = {}
        self.users: dict[int, FakeUser] = {}
        self.messages: dict[tuple[int, int], FakeMessage] = {}
        self.created: list[FakeMessage] = []
        self.added_roles: list[tuple[int, int, str | None]] = []
        self.removed_roles: list[tuple[int, int, str | None]] = []
        self.kicked: list[tuple[int, str | None]] = []
        self.banned: list[tuple[int, str | None]] = []
        self.unbanned: list[tuple[int, str | None]] = []
        self.deleted: list[tuple[int, int]] = []
        self.edited: list[tuple[FakeMessage, dict[str, Any]]] = []
        self.reactions: list[tuple[int, int, str]] = []
        self.channel_edits: list[tuple[int, dict[str, Any]]] = []
        self.guild_edits: list[tuple[int, dict[str, Any]]] = []
        self.welcome_screen_edits: list[tuple[int, dict[str, Any]]] = []
        # interaction endpoints (see the block below)
        self.interaction_log: dict[str, list[Any]] = {
            "responses": [],  # (token, ResponseType, payload)
            "edits": [],  # (token, message_id, payload)
            "deletes": [],  # (token, message_id)
            "followups": [],  # (token, payload)
            "modals": [],  # (token, title, custom_id, component)
        }
        self.responded_tokens: set[str] = set()
        self.token_response_types: dict[str, hikari.ResponseType] = {}
        self.webhook_messages: dict[str, FakeMessage] = {}
        self._known_message_ids: dict[int, str] = {}
        self._mint = itertools.count(1001)

    async def add_role_to_member(
        self,
        _guild: int,
        user: int,
        role: int,
        *,
        reason: str | None = None,
    ) -> None:
        self.added_roles.append((user, role, reason))
        member = self.members.get((_guild, user))
        if member is not None:
            member.role_ids.add(role)

    async def remove_role_from_member(
        self,
        _guild: int,
        user: int,
        role: int,
        *,
        reason: str | None = None,
    ) -> None:
        self.removed_roles.append((user, role, reason))
        member = self.members.get((_guild, user))
        if member is not None:
            member.role_ids.discard(role)

    async def kick_member(
        self,
        _guild: int,
        user: int,
        *,
        reason: str | None = None,
    ) -> None:
        self.kicked.append((user, reason))

    async def ban_member(
        self,
        _guild: int,
        user: int,
        *,
        reason: str | None = None,
        delete_message_seconds: int = 0,
    ) -> None:
        self.banned.append((user, reason))

    async def unban_member(
        self,
        _guild: int,
        user: int,
        *,
        reason: str | None = None,
    ) -> None:
        self.unbanned.append((user, reason))

    async def fetch_member(
        self, guild_id: int, user_id: int
    ) -> FakeMember:
        member = self.members.get((guild_id, user_id))
        if member is None:
            raise _not_found("member not found")
        return member

    async def fetch_guild_channels(
        self,
        guild_id: int,
    ) -> list[FakeChannel]:
        """The guild's channels (the cluster blast zone reads this)."""
        guild = self.guilds.get(guild_id)
        if guild is None:
            return []
        return list(guild.channels.values())

    async def fetch_user(self, user_id: int) -> FakeUser:
        user = self.users.get(user_id)
        if user is not None:
            return user
        for (_gid, uid), member in self.members.items():
            if uid == user_id:
                return member
        raise _not_found("user not found")

    async def fetch_message(
        self, channel_id: int, message_id: int
    ) -> FakeMessage:
        message = self.messages.get((channel_id, message_id))
        if message is None:
            raise _not_found("message not found")
        return message

    def fetch_messages(self, channel_id: int, **kwargs: Any) -> Any:
        """Async-iterate the recorded messages for a channel."""

        async def _gen() -> Any:
            for m in sorted(
                (
                    m
                    for (cid, _mid), m in self.messages.items()
                    if cid == channel_id
                ),
                key=lambda m: m.id,
            ):
                yield m

        return _gen()

    async def edit_message(
        self,
        channel_id: int,
        message_id: int,
        **kwargs: Any,
    ) -> FakeMessage:
        message = await self.fetch_message(channel_id, message_id)
        self.edited.append((message, kwargs))
        return message

    async def create_message(
        self,
        channel_id: int,
        content: Any = hikari.UNDEFINED,
        **kwargs: Any,
    ) -> FakeMessage:
        """Create a standalone channel message (not an interaction response).

        Recorded in ``self.created`` and stored under ``self.messages`` so
        it is fetchable like a real message. ``embed``/``embeds`` kwargs
        land on the message so tests can assert the capture content.
        """
        message = FakeMessage(
            id=next(self._mint),
            content=content if content is not hikari.UNDEFINED else "",
            channel_id=channel_id,
        )
        message.create_kwargs = kwargs
        if "embeds" in kwargs:
            message.embeds = kwargs["embeds"]
        elif "embed" in kwargs:
            message.embeds = [kwargs["embed"]]
        self.messages[(channel_id, message.id)] = message
        self.created.append(message)
        return message

    async def delete_message(
        self, channel_id: int, message_id: int
    ) -> None:
        self.deleted.append((channel_id, message_id))

    async def add_reaction(
        self, channel_id: int, message_id: int, emoji: str
    ) -> None:
        self.reactions.append((channel_id, message_id, emoji))

    async def edit_channel(self, channel_id: int, **kwargs: Any) -> None:
        self.channel_edits.append((channel_id, kwargs))

    async def edit_guild(self, guild: Any, **kwargs: Any) -> None:
        """Record a guild edit (banner, etc.) keyed by guild id."""
        gid = int(getattr(guild, "id", guild))
        self.guild_edits.append((gid, kwargs))

    async def edit_welcome_screen(self, guild: Any, **kwargs: Any) -> None:
        """Record a welcome-screen edit keyed by guild id."""
        gid = int(getattr(guild, "id", guild))
        self.welcome_screen_edits.append((gid, kwargs))

    # -- interaction endpoints ---------------------------------------------
    # Real hikari interaction objects (deserialized by the driver) call
    # these through ``bot.rest``. They model Discord's interaction-webhook
    # lifecycle so lifecycle bugs fail loudly instead of passing silently:
    #   * one initial response per interaction (a second call 404s)
    #   * webhook edits/deletes need an acked (responded) interaction
    #   * the addressed message must exist and belong to the token (or be
    #     the message the component interaction was created on)
    #   * ``@original`` resolves only after a response type that actually
    #     materialises a message (MESSAGE_* / DEFERRED_MESSAGE_UPDATE)
    # ``interaction_log`` keeps every call, token-tagged; the driver
    # snapshots it before a dispatch and diffs after.

    def _mint_message(self, token: str) -> FakeMessage:
        """A message id Discord would assign to a webhook message."""
        mid = next(self._mint)
        message = FakeMessage(id=mid, content="")
        self._known_message_ids[mid] = token
        self.webhook_messages[token] = message
        return message

    def register_source_message(self, token: str, message_id: int) -> None:
        """The message a component interaction was created on.

        Discord lets a click's webhook manage the message the button lives
        on once the click is acked — record it so the fake allows exactly
        that and nothing else cross-token.
        """
        self._known_message_ids.setdefault(message_id, token)

    def _original_addressable(self, token: str) -> bool:
        """True when ``@original`` resolves for this interaction."""
        return self.token_response_types.get(token) in (
            hikari.ResponseType.MESSAGE_CREATE,
            hikari.ResponseType.MESSAGE_UPDATE,
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE,
        )

    def _check_webhook(self, token: str, message: Any) -> FakeMessage:
        """Discord's webhook rules: acked token + an addressable message."""
        if token not in self.responded_tokens:
            raise _not_found("Unknown Webhook")
        mid = getattr(message, "id", message)
        if str(mid) == "@original":
            return self.webhook_messages.get(token) or FakeMessage(id=0)
        if self._known_message_ids.get(int(mid)) != token:
            raise _not_found("Unknown Message")
        return next(
            (
                m
                for m in self.webhook_messages.values()
                if m.id == int(mid)
            ),
            FakeMessage(id=int(mid)),
        )

    async def create_interaction_response(
        self,
        interaction: int,
        token: str,
        response_type: hikari.ResponseType,
        content: Any = hikari.UNDEFINED,
        **kwargs: Any,
    ) -> None:
        if token in self.responded_tokens:
            raise _not_found("Unknown Webhook")
        self.responded_tokens.add(token)
        self.token_response_types[token] = response_type
        self.interaction_log["responses"].append(
            (token, response_type, {"content": content, **kwargs})
        )
        if response_type in (
            hikari.ResponseType.MESSAGE_CREATE,
            hikari.ResponseType.MESSAGE_UPDATE,
        ):
            self._mint_message(token)

    async def create_modal_response(
        self,
        interaction: int,
        token: str,
        *,
        title: str,
        custom_id: str,
        component: Any = hikari.UNDEFINED,
        components: Any = hikari.UNDEFINED,
    ) -> None:
        if token in self.responded_tokens:
            raise _not_found("Unknown Webhook")
        self.responded_tokens.add(token)
        self.token_response_types[token] = hikari.ResponseType.MODAL
        self.interaction_log["modals"].append(
            {
                "token": token,
                "title": title,
                "custom_id": custom_id,
                "component": component,
                "components": components,
            }
        )

    async def edit_webhook_message(
        self,
        webhook: int,
        token: str,
        message: Any,
        **kwargs: Any,
    ) -> FakeMessage:
        target = self._check_webhook(token, message)
        mid = getattr(message, "id", message)
        self.interaction_log["edits"].append((token, mid, kwargs))
        return target

    async def edit_interaction_response(
        self,
        application: int,
        token: str,
        content: Any = hikari.UNDEFINED,
        **kwargs: Any,
    ) -> FakeMessage:
        """PATCH the interaction's initial response (``@original``)."""
        if not self._original_addressable(token):
            raise _not_found("Unknown Webhook")
        self.interaction_log["edits"].append(
            (token, "@original", {"content": content, **kwargs})
        )
        target = self.webhook_messages.get(token)
        if target is None:
            target = self._mint_message(token)
        return target

    async def delete_webhook_message(
        self, webhook: int, token: str, message: Any
    ) -> None:
        self._check_webhook(token, message)
        mid = getattr(message, "id", message)
        self.interaction_log["deletes"].append((token, mid))

    async def delete_interaction_response(
        self, application: int, token: str
    ) -> None:
        """DELETE the interaction's initial response (``@original``)."""
        if not self._original_addressable(token):
            raise _not_found("Unknown Webhook")
        self.interaction_log["deletes"].append((token, "@original"))

    async def execute_webhook(
        self, webhook: int, token: str, **kwargs: Any
    ) -> FakeMessage:
        if token not in self.responded_tokens:
            raise _not_found("Unknown Webhook")
        self.interaction_log["followups"].append((token, kwargs))
        return self._mint_message(token)

    async def fetch_interaction_response(
        self, application: int, token: str
    ) -> FakeMessage:
        if token not in self.responded_tokens:
            raise _not_found("Unknown Webhook")
        message = self.webhook_messages.get(token)
        if message is None:
            # no message exists yet (e.g. only a bare defer was sent)
            raise _not_found("Unknown Message")
        return message

    async def fetch_application(self) -> Any:
        """The bot's own application (owner checks read ``owner.id``)."""
        return SimpleNamespace(
            owner=FakeUser(id=1, name="owner", bot=True), team=None
        )


# -- Context / Interaction -------------------------------------------------


@dataclass
class SentMessage:
    """One recorded ``ctx.respond(...)`` — what a command "sent" in a test."""

    content: str | None = None
    embed: hikari.Embed | None = None
    embeds: list[hikari.Embed] | None = None
    component: Any = None
    components: list[Any] | None = None
    flags: int = 0
    ephemeral: bool = False
    attachment: Any = None


class FakeInteraction:
    """Minimal interaction stand-in (component/modal fields come later)."""

    def __init__(
        self,
        *,
        id: int = 1,
        member: FakeMember | None = None,
        user: FakeUser | None = None,
        guild_id: int | None = None,
        channel_id: int | None = None,
        custom_id: str | None = None,
    ) -> None:
        self.id = id
        self.member = member
        self.user = user or member
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.custom_id = custom_id
        self.initial_response_type: hikari.ResponseType | None = None
        self.initial_response: dict[str, Any] = {}

    async def create_initial_response(
        self,
        response_type: hikari.ResponseType,
        content: Any = hikari.UNDEFINED,
        **kwargs: Any,
    ) -> None:
        """Record the interaction's initial response (like FakeRest)."""
        self.initial_response_type = response_type
        self.initial_response = {"content": content, **kwargs}


class FakeClient:
    """Minimal lightbulb-client stand-in: commands reach the bot via ``app``."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._attached_menus: set[object] = set()
        self._attached_modals: dict[str, object] = {}
        # lightbulb's prefab hooks probe this for HOOK_INJECT_ALL_PARAMS
        self._features: set[object] = set()
        self._owner_ids: set[int] | None = {1}


class FakeContext:
    """A lightbulb-style context that records ``respond`` calls.

    Satisfies the ``window.Sendable`` protocol (``respond(content, flags=)``)
    and the lightbulb ``Context`` surface the ported cogs use (``member``,
    ``user``, ``options``, ``interaction``, ``client``, ``respond``,
    ``defer``, ``edit_response``, ``delete_response``).
    """

    def __init__(
        self,
        *,
        bot: Any,
        member: FakeMember,
        guild: FakeGuild,
        channel: FakeChannel,
        options: dict[str, Any] | None = None,
        interaction: FakeInteraction | None = None,
    ) -> None:
        self.bot = bot
        self.member = member
        self.user: FakeUser = member
        self.guild_id = guild.id
        self.channel_id = channel.id
        self.options = options or {}
        self.interaction = interaction or FakeInteraction(
            member=member,
            guild_id=guild.id,
            channel_id=channel.id,
        )
        self.client = FakeClient(bot)
        self.window: Any = None  # set by the windowed decorator
        self.sent: list[SentMessage] = []
        self.deferred: bool = False
        self.modals: list[Any] = []
        self.edits: list[dict[str, Any]] = []
        self.deleted: list[int] = []

    async def respond(
        self,
        content: str | None = None,
        *,
        embed: hikari.Embed | None = None,
        embeds: list[hikari.Embed] | None = None,
        component: Any = None,
        components: list[Any] | None = None,
        flags: int = 0,
        attachment: Any = None,
        **kwargs: Any,
    ) -> int:
        self.sent.append(
            SentMessage(
                content=content,
                embed=embed,
                embeds=embeds,
                component=component,
                components=components,
                flags=flags,
                ephemeral=bool(flags & hikari.MessageFlag.EPHEMERAL),
                attachment=attachment,
            )
        )
        return 1  # the response message id

    async def defer(self, *, flags: int = 0) -> None:
        self.deferred = True

    async def create_modal_response(self, modal: Any, /) -> None:
        self.modals.append(modal)

    async def edit_response(
        self, response_id: int, **kwargs: Any
    ) -> FakeMessage:
        self.edits.append({"response_id": response_id, **kwargs})
        return FakeMessage(id=response_id)

    async def delete_response(self, response_id: int) -> None:
        self.deleted.append(response_id)

    async def fetch_response(self, response_id: int) -> FakeMessage:
        """The response message — the fake responds with message id 1."""
        return FakeMessage(id=1)


class FakeMenuContext:
    """Lightbulb MenuContext stand-in: records respond/edit/stop calls."""

    def __init__(self, interaction: FakeInteraction) -> None:
        self.interaction = interaction
        self.channel_id: int = interaction.channel_id or 99
        self.sent: list[SentMessage] = []
        self.edits: list[dict[str, Any]] = []
        self.deleted: list[int] = []
        self.deferred: bool = False
        self.stopped: bool = False
        self._responded: bool = False
        self.fetched: list[int] = []

    async def respond(
        self,
        content: str | None = None,
        *,
        embed: hikari.Embed | None = None,
        embeds: list[hikari.Embed] | None = None,
        component: Any = None,
        flags: int = 0,
        **kwargs: Any,
    ) -> int:
        self.sent.append(
            SentMessage(
                content=content,
                embed=embed,
                embeds=embeds,
                component=component,
                flags=flags,
                ephemeral=bool(flags & hikari.MessageFlag.EPHEMERAL),
            )
        )
        # like lightbulb: the FIRST response returns the initial-response
        # sentinel (not a message id); later responses return the message id
        if not self._responded:
            self._responded = True
            return utils.INITIAL_RESPONSE_IDENTIFIER
        return 42  # the response message id

    async def defer(self, *, flags: int = 0, **kwargs: Any) -> None:
        self.deferred = True

    async def edit_response(self, response_id: int, **kwargs: Any) -> None:
        self.edits.append({"response_id": response_id, **kwargs})

    async def delete_response(self, response_id: int) -> None:
        self.deleted.append(response_id)

    async def fetch_response(self, response_id: int) -> FakeMessage:
        """The response message for the sentinel (id 7 by default)."""
        self.fetched.append(response_id)
        return FakeMessage(id=7)

    def stop_interacting(self) -> None:
        self.stopped = True


class FakeMessageCreateEvent:
    """hikari.MessageCreateEvent stand-in for the exp pipeline listener."""

    def __init__(self, message: FakeMessage, app: Any = None) -> None:
        self.message = message
        self.app = app
        self.is_human: bool = not bool(
            message.author.bot if message.author is not None else False
        )


class FakeMemberUpdateEvent:
    """hikari.MemberUpdateEvent stand-in for the welcome listener."""

    def __init__(
        self,
        *,
        member: FakeMember,
        old_member: FakeMember | None = None,
        guild_id: int = 2,
        app: Any = None,
    ) -> None:
        self.member = member
        self.old_member = old_member
        self.guild_id = guild_id
        self.app = app


class FakeComponentInteraction:
    """hikari.ComponentInteraction stand-in for persistent-button handlers."""

    def __init__(
        self,
        *,
        user: FakeMember | FakeUser,
        message_id: int = 555,
        channel_id: int = 99,
        guild_id: int = 2,
        custom_id: str = "counter:baka",
    ) -> None:
        self.id = 1
        self.user = user
        self.message = FakeMessage(id=message_id, channel_id=channel_id)
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.custom_id = custom_id
        self.responses: list[
            tuple[hikari.ResponseType, dict[str, Any]]
        ] = []
        self.modals: list[dict[str, Any]] = []

    async def create_initial_response(
        self,
        response_type: hikari.ResponseType,
        content: str | None = None,
        *,
        embed: hikari.Embed | None = None,
        embeds: list[hikari.Embed] | None = None,
        flags: int = 0,
        **kwargs: Any,
    ) -> None:
        self.responses.append(
            (
                response_type,
                {
                    "content": content,
                    "embed": embed,
                    "embeds": embeds,
                    "flags": flags,
                    **kwargs,
                },
            )
        )

    async def create_modal_response(
        self,
        title: str,
        custom_id: str,
        *,
        component: Any = None,
        components: Any = None,
        **kwargs: Any,
    ) -> None:
        self.modals.append(
            {
                "title": title,
                "custom_id": custom_id,
                "component": component,
                "components": components,
            }
        )


class FakeModalContext:
    """lightbulb ModalContext stand-in: value lookup + respond recording."""

    def __init__(
        self,
        values: dict[object, str] | None = None,
        user: FakeMember | FakeUser | None = None,
    ) -> None:
        self._values = values or {}
        self.user = user
        self.sent: list[dict[str, Any]] = []

    def value_for(self, input: object) -> str | None:
        return self._values.get(input)

    async def respond(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> int:
        self.sent.append({"content": content, "ephemeral": ephemeral})
        return 1


def first_button_custom_id(
    component: hikari.api.ComponentBuilder,
) -> str:
    """custom_id of a builder's first button (typed escape for components)."""
    from hikari.impl import InteractiveButtonBuilder

    row = component
    for child in row.components:
        if isinstance(child, InteractiveButtonBuilder):
            return child.custom_id or ""
    return ""


def menu_button(menu: Any, index: int = 0) -> Any:
    """A lightbulb menu's first-row button at ``index`` (callback drives it)."""
    return cast(list[Any], menu._rows[0])[index]  # pyright: ignore[reportPrivateUsage]


def rest_of(bot: Any) -> FakeRest:
    """The bot's rest client, typed as the fake (it IS the fake in tests)."""
    return cast(FakeRest, bot.rest)


async def invoke_command(
    command: object, ctx: FakeContext, **options: Any
) -> None:
    """Run a lightbulb command class's invoke with seeded option values.

    lightbulb fills ``_localized_name`` during client registration; without
    a client, seed it from the declared names so the option descriptors
    resolve. Unset options fall back to their declared default.
    """
    cmd = cast(Any, command)
    for name, data in cmd._command_data.options.items():  # pyright: ignore[reportPrivateUsage]
        descriptor = type(cmd).__dict__[name]
        descriptor._data._localized_name = name  # pyright: ignore[reportPrivateUsage]
        default = data.default  # pyright: ignore[reportPrivateUsage]
        if default is hikari.UNDEFINED:
            default = None
        cmd._resolved_option_cache[name] = options.get(  # pyright: ignore[reportPrivateUsage]
            name, default
        )
    cmd._current_context = ctx  # pyright: ignore[reportPrivateUsage]
    await cmd.invoke(ctx)


def seed_bot(
    bot: Any,
    *,
    cache: FakeCache | None = None,
    rest: FakeRest | None = None,
) -> None:
    """Inject fakes into a hikari bot's cache/rest properties.

    ``GatewayBot.cache`` / ``.rest`` are properties over ``_cache``/``_rest``
    (plain instance attrs), so assignment works offline.
    """
    if cache is not None:
        bot._cache = cache
    if rest is not None:
        bot._rest = rest
