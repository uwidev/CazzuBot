# pyright: reportMissingSuperCall=false, reportIncompatibleVariableOverride=false, reportAttributeAccessIssue=false, reportAssignmentType=false, reportIncompatibleMethodOverride=false
"""Typed fakes for discord model objects, used across the test suite.

Strategy: subclass the real discord.py model and never call ``super().__init__``
— the real constructors need a live ``ConnectionState``. Parent attributes that
are *properties* (data descriptors) are re-declared on the subclass, because
instance assignment cannot shadow a descriptor and the inherited getter reads
discord.py internals (``_user``, ``_state``, ...). Plain/slot attributes are
assigned directly. Anything a cog calls that we forgot to fake inherits the
parent implementation and raises loudly at the test — a feature, not a bug:
the traceback names the exact attribute to re-declare.

Pure-data discord classes (``discord.Embed``, ``discord.Permissions``,
``discord.Colour``) are NOT faked here — they construct fine offline.

The ``# pyright:`` file-level directives above are scoped to THIS file only:
pyright's strict override rules assume subclasses follow normal inheritance
(super().__init__ call, compatible property overrides), which is impossible
for discord.py models without a live connection. Everything outside this
file stays under the strict project rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast, override

import discord
from discord.ext import commands

from cazzubot.window import CommandWindow


# -- Asset ----------------------------------------------------------------


class FakeAsset(discord.Asset):
    """A URL-only asset (``display_avatar.url`` is all cogs read)."""

    def __init__(self, url: str) -> None:
        self._url = url

    @property
    @override
    def url(self) -> str:
        return self._url


# -- User / Member --------------------------------------------------------


class FakeUser(discord.User):
    def __init__(
        self,
        *,
        id: int,
        name: str,
        bot: bool = False,
    ) -> None:
        self.id = id
        self.name = name
        self.bot = bot
        self._fake_avatar = FakeAsset(
            f"https://example.com/avatar/{id}.png"
        )

    @override
    def __str__(self) -> str:
        return self.name

    @property
    @override
    def display_name(self) -> str:
        return self.name

    @property
    @override
    def mention(self) -> str:
        return f"<@{self.id}>"

    @property
    @override
    def display_avatar(self) -> discord.Asset:
        return self._fake_avatar


class FakeMember(discord.Member):
    guild: FakeGuild | None  # narrow parent's declared attr for readers

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
        self._id = id
        self._name = name
        self._bot = bot
        self._created_at = datetime.now(timezone.utc)
        self.guild = guild
        self.nick: str | None = None
        self.joined_at: datetime | None = None
        self._fake_roles = roles or []
        self._administrator = administrator
        self.added_roles: list[discord.Role] = []
        self.removed_roles: list[discord.Role] = []
        self.kicked: list[str | None] = []
        self.banned: list[str | None] = []
        self.pending: bool = False

    @override
    def __str__(self) -> str:
        return self._name

    # -- re-declared properties (parent defines these as properties) ------

    @property
    @override
    def id(self) -> int:
        return self._id

    @property
    @override
    def name(self) -> str:
        return self._name

    @property
    @override
    def bot(self) -> bool:
        return self._bot

    @property
    @override
    def created_at(self) -> datetime:
        return self._created_at

    @property
    @override
    def display_name(self) -> str:
        return self.nick or self._name

    @property
    @override
    def mention(self) -> str:
        return f"<@{self._id}>"

    @property
    @override
    def display_avatar(self) -> discord.Asset:
        return FakeAsset(f"https://example.com/avatar/{self._id}.png")

    @property
    @override
    def roles(self) -> list[FakeRole]:
        return self._fake_roles

    @property
    @override
    def guild_permissions(self) -> discord.Permissions:
        return discord.Permissions(administrator=self._administrator)

    # -- recorders: never touch the real API, record the call -------------

    @override
    async def add_roles(
        self, *roles: discord.Role, reason: str | None = None
    ) -> None:
        self.added_roles.extend(roles)

    @override
    async def remove_roles(
        self, *roles: discord.Role, reason: str | None = None
    ) -> None:
        self.removed_roles.extend(roles)

    @override
    async def kick(
        self, reason: str | None = None, **_kwargs: Any
    ) -> None:
        self.kicked.append(reason)

    @override
    async def ban(self, reason: str | None = None, **_kwargs: Any) -> None:
        self.banned.append(reason)


# -- Role / Guild / Channel ------------------------------------------------


class FakeRole(discord.Role):
    def __init__(
        self,
        *,
        id: int,
        name: str,
        permissions: discord.Permissions | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self._fake_permissions = permissions or discord.Permissions()

    @property
    @override
    def mention(self) -> str:
        return f"<@&{self.id}>"

    @property
    @override
    def permissions(self) -> discord.Permissions:
        return self._fake_permissions


class FakeGuild(discord.Guild):
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
        self._me: FakeMember | None = None
        self._fake_members: dict[int, FakeMember] = {}
        self._fake_roles: dict[int, FakeRole] = {}
        self._fake_channels: dict[int, FakeChannel] = {}
        self.unbanned: list[tuple[discord.User, str | None]] = []

    @property
    @override
    def me(self) -> FakeMember | None:
        return self._me

    @property
    @override
    def members(self) -> list[FakeMember]:
        return list(self._fake_members.values())

    @property
    @override
    def roles(self) -> list[FakeRole]:
        return list(self._fake_roles.values())

    @override
    def get_member(self, user_id: int) -> FakeMember | None:
        return self._fake_members.get(user_id)

    @override
    def get_role(self, role_id: int) -> FakeRole | None:
        return self._fake_roles.get(role_id)

    @override
    def get_channel(self, channel_id: int) -> FakeChannel | None:
        return self._fake_channels.get(channel_id)

    @override
    def _resolve_channel(
        self, channel_id: int | None, /
    ) -> FakeChannel | None:
        """Bot.get_channel resolves through this (private, but stable)."""
        if channel_id is None:
            return None
        return self._fake_channels.get(channel_id)

    @override
    async def fetch_member(self, user_id: int) -> FakeMember:
        """Cache-backed stand-in for the network fetch."""
        member = self._fake_members.get(user_id)
        if member is None:
            raise discord.NotFound(
                cast(Any, SimpleNamespace(status=404, reason="not found")),
                "member not found",
            )
        return member

    @override
    async def unban(
        self, user: discord.User, *, reason: str | None = None
    ) -> None:
        self.unbanned.append((user, reason))

    def add_member(self, member: FakeMember) -> None:
        self._fake_members[member.id] = member
        member.guild = self

    def add_role(self, role: FakeRole) -> None:
        self._fake_roles[role.id] = role

    def add_channel(self, channel: FakeChannel) -> None:
        self._fake_channels[channel.id] = channel


class FakeChannel(discord.TextChannel):
    guild: FakeGuild | None  # narrow parent's declared attr for readers

    def __init__(
        self,
        *,
        id: int,
        name: str = "general",
        guild: FakeGuild | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.guild = guild
        self.sent: list[dict[str, Any]] = []
        self.messages: list[FakeMessage] = []
        self.edits: list[dict[str, Any]] = []

    @property
    @override
    def type(self) -> discord.ChannelType:
        return discord.ChannelType.text

    @property
    @override
    def mention(self) -> str:
        return f"<#{self.id}>"

    @override
    def permissions_for(
        self, member: discord.Member | discord.User
    ) -> discord.Permissions:
        """Simplification: channel perms == guild perms (admin ⇒ all)."""
        if isinstance(member, FakeMember):
            perms = member.guild_permissions
            if perms.administrator:
                return discord.Permissions.all()
            return perms
        return discord.Permissions()

    @override
    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)

    @override
    async def send(
        self, content: str | None = None, **kwargs: Any
    ) -> FakeMessage:
        self.sent.append({"content": content, **kwargs})
        message = FakeMessage(
            id=1,
            content=content or "",
            guild=self.guild,
            channel=self,
        )
        self.messages.append(message)
        return message

    @override
    async def fetch_message(self, message_id: int) -> FakeMessage:
        """Cache-backed stand-in for the network fetch."""
        for message in self.messages:
            if message.id == message_id:
                return message
        raise discord.NotFound(
            cast(Any, SimpleNamespace(status=404, reason="not found")),
            "message not found",
        )

    @override
    async def history(self, **kwargs: Any):
        """Yield the recorded messages (oldest first, like the real API)."""
        for message in self.messages:
            yield message

    @override
    def typing(self):
        """No-op async context manager standing in for channel.typing()."""

        class _Typing:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: object) -> bool:
                return False

        return _Typing()


# -- Message / Interaction -------------------------------------------------


class FakeMessage(discord.Message):
    author: FakeMember | FakeUser | None
    guild: FakeGuild | None
    channel: FakeChannel | None

    def __init__(
        self,
        *,
        id: int = 1,
        content: str = "",
        author: FakeMember | FakeUser | None = None,
        guild: FakeGuild | None = None,
        channel: FakeChannel | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.content = content
        self.author = author
        self.guild = guild
        self.channel = channel
        self._created_at = created_at or datetime.now(timezone.utc)
        self.deleted = False
        self.reactions: list[str] = []
        self.edits: list[dict[str, Any]] = []
        self.embeds: list[discord.Embed] = []
        self.attachments: list[object] = []

    @property
    @override
    def created_at(self) -> datetime:
        return self._created_at

    @override
    async def delete(self, **_kwargs: Any) -> None:
        self.deleted = True

    @override
    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)

    @override
    async def add_reaction(self, reaction: object, **_kwargs: Any) -> None:
        self.reactions.append(str(reaction))


class FakeInteractionResponse(discord.InteractionResponse):
    """Recorder standing in for ``discord.InteractionResponse``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @override
    async def send_message(
        self, content: str | None = None, **kwargs: Any
    ) -> None:
        self.calls.append(("send_message", {"content": content, **kwargs}))

    @override
    async def edit_message(self, **kwargs: Any) -> None:
        self.calls.append(("edit_message", kwargs))

    async def edit_original_response(self, **kwargs: Any) -> None:
        self.calls.append(("edit_original_response", kwargs))

    @override
    async def defer(self, **kwargs: Any) -> None:
        self.calls.append(("defer", kwargs))

    @override
    async def send_modal(self, modal: discord.ui.Modal, /) -> None:
        self.calls.append(("send_modal", {"modal": modal}))


class FakeFollowup:
    """Recorder for ``interaction.followup`` (webhook-style sends)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.messages: list[FakeMessage] = []

    async def send(
        self, content: str | None = None, **kwargs: Any
    ) -> FakeMessage:
        self.sent.append({"content": content, **kwargs})
        message = FakeMessage(id=2, content=content or "")
        self.messages.append(message)
        return message


class FakeInteraction(discord.Interaction[Any]):
    response: FakeInteractionResponse  # override parent's declared type
    followup: FakeFollowup  # parent declares this as a Webhook

    def __init__(
        self,
        *,
        id: int = 1,
        user: FakeMember | FakeUser,
        message: FakeMessage | None = None,
        data: dict[str, Any] | None = None,
        guild: FakeGuild | None = None,
        channel_id: int | None = None,
    ) -> None:
        self.id = id
        self.user = user
        self.message = message
        self.data = data or {}
        self._guild = guild
        self._channel_id = channel_id
        self.response = FakeInteractionResponse()
        self.followup = FakeFollowup()
        self.original_message = FakeMessage(id=555)

    @property
    @override
    def guild(self) -> FakeGuild | None:
        return self._guild

    @property
    @override
    def channel_id(self) -> int | None:
        return self._channel_id

    @override
    async def original_response(self) -> FakeMessage:
        """Stand-in for the followup fetch (the recorded message)."""
        return self.original_message


# -- Context ---------------------------------------------------------------


@dataclass
class SentMessage:
    """One recorded ``ctx.send(...)`` — what a command "sent" in a test."""

    content: str | None = None
    embed: discord.Embed | None = None
    view: discord.ui.View | None = None
    ephemeral: bool = False


class FakeContext(commands.Context[Any]):
    """A command context that records sends instead of touching Discord."""

    # Narrow the parent's declared attribute types to our fakes so tests
    # stay fully typed (basedpyright reports a fake attribute at dev time).
    bot: commands.Bot
    author: FakeMember | FakeUser
    guild: FakeGuild | None
    channel: FakeChannel
    message: FakeMessage
    window: CommandWindow

    def __init__(
        self,
        *,
        bot: commands.Bot,
        author: FakeMember | FakeUser,
        guild: FakeGuild | None,
        channel: FakeChannel,
        message: FakeMessage | None = None,
        invoked_with: str = "test",
    ) -> None:
        self.bot = bot
        self.author = author
        self.guild = guild
        self.channel = channel
        self.message = message or FakeMessage()
        self.invoked_with = invoked_with
        self.interaction: discord.Interaction[Any] | None = None
        self.window = CommandWindow(self)
        self.sent: list[SentMessage] = []
        self.returned: list[FakeMessage] = []

    @override
    async def send(
        self,
        content: str | None = None,
        **kwargs: Any,
    ) -> FakeMessage:
        self.sent.append(
            SentMessage(
                content=content,
                embed=kwargs.get("embed"),
                view=kwargs.get("view"),
                ephemeral=bool(kwargs.get("ephemeral", False)),
            )
        )
        message = FakeMessage(
            id=1,
            content=content or "",
            author=self.author,
            guild=self.guild,
            channel=self.channel,
        )
        self.returned.append(message)
        return message

    @override
    async def reply(
        self, content: str | None = None, **kwargs: Any
    ) -> FakeMessage:
        return await self.send(content, **kwargs)


def first_button_custom_id(view: discord.ui.View) -> str:
    """custom_id of a view's first button (typed escape for ``Item[]``)."""
    button = view.children[0]
    assert isinstance(button, discord.ui.Button)
    return button.custom_id or ""


def seed_guild(bot: commands.Bot, guild: FakeGuild) -> None:
    """Register a fake guild in the bot's connection cache.

    Makes ``bot.guild`` / ``bot.guilds`` / ``get_guild`` resolve offline
    (the connection cache is a plain dict in discord.py 2.7.1).
    """
    bot._connection._guilds[guild.id] = guild  # pyright: ignore[reportPrivateUsage]
