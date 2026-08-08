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
from typing import Any, cast

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
        self.member: FakeMember | None = (
            author if isinstance(author, FakeMember) else None
        )
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.created_at = created_at or datetime.now(timezone.utc)
        self.embeds = embeds or []
        self.attachments: list[object] = []
        self.components: list[Any] = []
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
        self.users: dict[int, FakeUser] = {}
        self.messages: dict[tuple[int, int], FakeMessage] = {}
        self.added_roles: list[tuple[int, int, str | None]] = []
        self.removed_roles: list[tuple[int, int, str | None]] = []
        self.kicked: list[tuple[int, str | None]] = []
        self.banned: list[tuple[int, str | None]] = []
        self.unbanned: list[tuple[int, str | None]] = []
        self.deleted: list[tuple[int, int]] = []
        self.edited: list[tuple[FakeMessage, dict[str, Any]]] = []
        self.reactions: list[tuple[int, int, str]] = []
        self.typing_channels: list[int] = []
        self.channel_edits: list[tuple[int, dict[str, Any]]] = []

    async def add_role_to_member(
        self,
        _guild: int,
        user: int,
        role: int,
        *,
        reason: str | None = None,
    ) -> None:
        self.added_roles.append((user, role, reason))

    async def remove_role_from_member(
        self,
        _guild: int,
        user: int,
        role: int,
        *,
        reason: str | None = None,
    ) -> None:
        self.removed_roles.append((user, role, reason))

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
        message.edits.append(kwargs)
        self.edited.append((message, kwargs))
        return message

    async def delete_message(
        self, channel_id: int, message_id: int
    ) -> None:
        self.deleted.append((channel_id, message_id))

    async def add_reaction(
        self, channel_id: int, message_id: int, emoji: str
    ) -> None:
        self.reactions.append((channel_id, message_id, emoji))

    async def trigger_typing(self, channel_id: int) -> None:
        self.typing_channels.append(channel_id)

    async def edit_channel(self, channel_id: int, **kwargs: Any) -> None:
        self.channel_edits.append((channel_id, kwargs))


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


class FakeClient:
    """Minimal lightbulb-client stand-in: commands reach the bot via ``app``."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._attached_menus: set[object] = set()
        self._attached_modals: dict[str, object] = {}
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
        return 42  # the response message id

    async def defer(self, *, flags: int = 0) -> None:
        self.deferred = True

    async def edit_response(self, response_id: int, **kwargs: Any) -> None:
        self.edits.append({"response_id": response_id, **kwargs})

    async def delete_response(self, response_id: int) -> None:
        self.deleted.append(response_id)

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
        custom_id: str = "counter:baka",
    ) -> None:
        self.id = 1
        self.user = user
        self.message = FakeMessage(id=message_id, channel_id=channel_id)
        self.channel_id = channel_id
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
