"""Roles plugin — warn-only boot-time drift check for the role manifest.

Enforcement is manual (the CLI: ``uv run python -m cazzubot.roles``); this
plugin only reports manifest drift in the boot logs, mirroring the
``verify_schema`` philosophy without ever auto-applying.

Setting: ``roles.manifest.path`` (default ``roles.manifest``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import hikari
from typing_extensions import override

from cazzubot import Plugin
from cazzubot.roles.parser import ManifestError, VALID_FLAGS, parse
from cazzubot.roles.plan import build_plan
from cazzubot.roles.snapshot import RoleSnapshot

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)


def _role_snapshot(role: hikari.Role, pos: int) -> RoleSnapshot:
    """Adapt a hikari role to the snapshot dict the plan engine consumes."""
    icon: str | None = None
    if role.unicode_emoji:
        icon = role.unicode_emoji
    elif role.icon_hash is not None:
        icon = str(role.make_icon_url())
    perms = [
        name
        for name in VALID_FLAGS
        if getattr(role.permissions, name, False)
    ]
    # hikari 2.5 has no RoleTags; managed roles are never user-manageable,
    # which is the only property the plan reads the tags for.
    tags = ["bot"] if role.is_managed else []
    color = int(role.color) if role.color is not None else 0
    return {
        "position": pos,
        "id": str(role.id),
        "name": role.name,
        "color": f"#{color:06x}" if color else None,
        "hoisted": role.is_hoisted,
        "mentionable": role.is_mentionable,
        "managed": role.is_managed,
        "permissions": perms,
        "icon": icon,
        "tags": tags,
    }


async def _snapshot_guild(
    bot: "CazzuBot", guild_id: int
) -> list[RoleSnapshot]:
    """The guild's roles top-down from a fresh REST fetch (cache lags)."""
    roles = sorted(
        await bot.rest.fetch_roles(guild_id),
        key=lambda r: r.position,
        reverse=True,
    )
    return [_role_snapshot(role, i) for i, role in enumerate(roles)]


class RolesPlugin(Plugin):
    name = "roles"
    _bot: "CazzuBot | None" = None

    @override
    async def on_load(self, bot: "CazzuBot") -> None:
        self._bot = bot
        # the guild is not available until the gateway is up; hook it there
        bot.subscribe(hikari.StartedEvent, self._check_once)

    @override
    async def on_unload(self, bot: "CazzuBot") -> None:
        bot.unsubscribe(hikari.StartedEvent, self._check_once)

    async def _check_once(self, _event: hikari.StartedEvent) -> None:
        bot = self._bot
        if bot is None:
            return
        raw = await bot.settings.get(
            "roles.manifest.path", "roles.manifest"
        )
        path = Path(str(raw))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            _log.info(
                "roles manifest %s not found — skipping drift check", path
            )
            return
        try:
            manifest = parse(text)
        except ManifestError as err:
            _log.warning(
                "roles manifest invalid (%s):\n%s",
                path,
                "\n".join(str(issue) for issue in err.issues),
            )
            return

        guild = bot.guild
        if guild is None:
            _log.warning("roles manifest: guild not available yet")
            return
        roles = await _snapshot_guild(bot, guild.id)
        bot_top_role_id: int | None = None
        me = guild.get_my_member()
        if me is not None:
            top = me.get_top_role()
            if top is not None:
                bot_top_role_id = top.id
        plan = build_plan(
            manifest,
            roles,
            bot_top_role_id=bot_top_role_id,
        )
        if plan.is_clean():
            if plan.strays:
                _log.info(
                    "roles manifest ok (%d unmanaged strays)",
                    len(plan.strays),
                )
            else:
                _log.info("roles manifest ok")
        else:
            _log.warning(
                "roles manifest drift — %s\n%s",
                plan.summary(),
                plan.render(),
            )


plugin = RolesPlugin()
