# pyright: reportAttributeAccessIssue=false
"""Typed fakes for hikari objects, used across the test suite.

Standalone classes — hikari models are immutable ``attrs`` objects with
``__slots__``, so the old discord.py "subclass without ``super().__init__``"
trick is impossible. The surface below is the HIKARI_MIGRATION.md freeze
list: member identity (``id``/``display_name``/``mention``/``avatar_url``),
role ids + permissions, rest-client spies for mutations, cache-backed
lookups, and a lightbulb-style command context whose ``respond`` records
sends.

Anything a ported cog calls that we forgot to fake raises ``AttributeError``
loudly at the test — a feature, not a bug: the traceback names the exact
attribute to add.

Pure-data hikari classes (``hikari.Embed``, ``hikari.Permissions``) are NOT
faked here — they construct fine offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import hikari


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
        self.type = hikari.ChannelType.GUILD_TEXT
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
    ) -> None:
        self.id = id
        self.content = content
        self.author = author
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.created_at = created_at or datetime.now(timezone.utc)
        self.embeds = embeds or []
        self.reactions: list[str] = []
        self.deleted = False
        self.edits: list[dict[str, Any]] = []


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
        self.members: dict[tuple[int, int], FakeMember] = {}
        self.messages: dict[tuple[int, int], FakeMessage] = {}
        self.added_roles: list[
            tuple[FakeMember, FakeRole, str | None]
        ] = []
        self.removed_roles: list[
            tuple[FakeMember, FakeRole, str | None]
        ] = []
        self.kicked: list[tuple[FakeMember, str | None]] = []
        self.banned: list[tuple[FakeMember, str | None]] = []
        self.unbanned: list[tuple[FakeUser, str | None]] = []
        self.deleted: list[FakeMessage] = []
        self.edited: list[tuple[FakeMessage, dict[str, Any]]] = []
        self.reactions: list[tuple[FakeMessage, str]] = []
        self.typing_channels: list[int] = []

    async def add_role_to_member(
        self,
        _guild: int,
        user: FakeMember,
        role: FakeRole,
        *,
        reason: str | None = None,
    ) -> None:
        self.added_roles.append((user, role, reason))

    async def remove_role_from_member(
        self,
        _guild: int,
        user: FakeMember,
        role: FakeRole,
        *,
        reason: str | None = None,
    ) -> None:
        self.removed_roles.append((user, role, reason))

    async def kick_member(
        self,
        _guild: int,
        user: FakeMember,
        *,
        reason: str | None = None,
    ) -> None:
        self.kicked.append((user, reason))

    async def ban_member(
        self,
        _guild: int,
        user: FakeMember,
        *,
        reason: str | None = None,
        delete_message_days: int = 0,
    ) -> None:
        self.banned.append((user, reason))

    async def unban_member(
        self,
        _guild: int,
        user: FakeUser,
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

    async def fetch_user(self, user_id: int) -> FakeUser:
        for (gid, uid), member in self.members.items():
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

    async def fetch_messages(
        self, channel_id: int, **kwargs: Any
    ) -> list[FakeMessage]:
        return [
            m
            for (cid, _mid), m in sorted(self.messages.items())
            if cid == channel_id
        ]

    async def edit_message(
        self,
        channel_id: int,
        message_id: int,
        **kwargs: Any,
    ) -> FakeMessage:
        message = await self.fetch_message(channel_id, message_id)
        message.edits.append(kwargs)
        return message

    async def delete_message(
        self, _channel_id: int, message: FakeMessage
    ) -> None:
        message.deleted = True
        self.deleted.append(message)

    async def add_reaction(
        self, channel_id: int, message_id: int, emoji: str
    ) -> None:
        message = await self.fetch_message(channel_id, message_id)
        message.reactions.append(emoji)
        self.reactions.append((message, emoji))

    async def trigger_typing(self, channel_id: int) -> None:
        self.typing_channels.append(channel_id)


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


class FakeContext:
    """A lightbulb-style context that records ``respond`` calls.

    Satisfies the ``window.Sendable`` protocol (``respond(content, flags=)``)
    and the lightbulb ``Context`` surface the ported cogs use (``member``,
    ``options``, ``interaction``, ``respond``, ``defer``).
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
        self.guild_id = guild.id
        self.channel_id = channel.id
        self.options = options or {}
        self.interaction = interaction or FakeInteraction(
            member=member,
            guild_id=guild.id,
            channel_id=channel.id,
        )
        self.sent: list[SentMessage] = []
        self.deferred: bool = False
        self.modals: list[Any] = []

    async def respond(
        self,
        content: str | None = None,
        *,
        embed: hikari.Embed | None = None,
        embeds: list[hikari.Embed] | None = None,
        component: Any = None,
        components: list[Any] | None = None,
        flags: int = 0,
        **kwargs: Any,
    ) -> FakeMessage:
        self.sent.append(
            SentMessage(
                content=content,
                embed=embed,
                embeds=embeds,
                component=component,
                components=components,
                flags=flags,
                ephemeral=bool(flags & hikari.MessageFlag.EPHEMERAL),
            )
        )
        return FakeMessage(
            id=1,
            content=content or "",
            author=self.member,
            guild_id=self.guild_id,
            channel_id=self.channel_id,
        )

    async def defer(self, *, flags: int = 0) -> None:
        self.deferred = True

    async def create_modal_response(self, modal: Any, /) -> None:
        self.modals.append(modal)


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
