"""Command-surface security policy guardrails.

Admin/owner-only commands must be invisible to regular members
(``default_member_permissions=ADMINISTRATOR``) wherever the framework
allows it — top-level commands and fully-gated groups — and every
DB/settings-mutating command must carry an execution-check hook even
when it can't be hidden (mixed groups like ``frog``/``exp``/``mod``).

``test_every_command_is_hidden_checked_or_user_facing`` sweeps the whole
command tree and fails if any command exists that is neither hidden,
check-gated, nor explicitly allowlisted as user-facing/self-service.
"""

from __future__ import annotations

from collections.abc import Sequence

import hikari

from cazzubot.bot import CazzuBot
from lightbulb.commands.commands import CommandBase
from lightbulb.commands.execution import ExecutionHook
from lightbulb.commands.groups import Group, SubGroup
from plugins.board.extension import board as board_group
from plugins.counter.extension import counter as counter_group
from plugins.dev.extension import calc as calc_group
from plugins.dev.extension import plugin_group
from plugins.fun.extension import story as story_group
from plugins.levels.extension import level as level_group
from plugins.misc.extension import misc as misc_group
from plugins.poll.extension import poll as poll_group
from plugins.ranks.extension import rank as rank_group
from plugins.welcome.extension import welcome as welcome_group

ADMIN = hikari.Permissions.ADMINISTRATOR

# Fully admin/owner-gated groups — every member must be invisible to
# non-admins (the group carries the permission; members inherit it).
HIDDEN_GROUPS: dict[tuple[str, ...], Group] = {
    ("board",): board_group,
    ("counter",): counter_group,
    ("level",): level_group,
    ("rank",): rank_group,
    ("welcome",): welcome_group,
    ("poll",): poll_group,
    ("misc",): misc_group,
    ("story",): story_group,
    # dev plugin (owner tooling, no enclosing group)
    ("calc",): calc_group,
    ("plugin",): plugin_group,
}

# Top-level leaf commands that must be invisible to non-admins.
HIDDEN_COMMANDS: set[tuple[str, ...]] = {
    ("owner",),
    ("archive_emojis",),
    ("scrape",),
    ("register_inktober",),
    ("scrape_inktober",),
}

# Visible-by-design: read-only or self-service user commands.
USER_FACING: set[tuple[str, ...]] = {
    ("hashiresoriyo",),
    ("info",),
    ("noot",),
    ("ping",),
    ("echo",),
    ("exp", "card"),
    ("exp", "lifetime"),
    ("exp", "top"),
    ("exp", "quiet", "list"),
    ("frog", "profile"),
    ("frog", "consume"),
    ("frog", "catalog"),
    ("frog", "lifetime"),
    ("inventory",),
}


def _command_tree(
    bot: CazzuBot,
) -> dict[tuple[str, ...], type[CommandBase]]:
    """path -> command class from lightbulb's registration map."""
    tree: dict[tuple[str, ...], type[CommandBase]] = {}
    for mapping in bot.lightbulb.invokable_commands.values():
        for path, collection in mapping.items():
            if collection.slash is None:
                continue
            tree[path] = collection.slash
    return tree


def _perms(
    cmd: Group | type[CommandBase],
) -> hikari.UndefinedOr[hikari.Permissions]:
    if isinstance(cmd, Group):
        return cmd.default_member_permissions
    return cmd._command_data.default_member_permissions  # pyright: ignore[reportPrivateUsage]


# Permission-gate hooks — the only kind that counts as "check-gated"
# (a cooldown/concurrency hook must not satisfy the security sweep).
_GATE_NAMES = {"owner_only", "has_permissions", "mod_gate"}


def _hooks(cmd: type[CommandBase]) -> Sequence[object]:
    return cmd._command_data.hooks  # pyright: ignore[reportPrivateUsage]


def _is_permission_gate(hook: object) -> bool:
    return isinstance(hook, ExecutionHook) and hook.name in _GATE_NAMES


def _gates(cmd: type[CommandBase]) -> list[object]:
    return [h for h in _hooks(cmd) if _is_permission_gate(h)]


def test_gated_groups_are_hidden() -> None:
    for path, group in HIDDEN_GROUPS.items():
        assert _perms(group) == ADMIN, (
            f"{path!r} must carry default_member_permissions=ADMINISTRATOR"
        )


def test_gated_top_level_commands_are_hidden(full_bot: CazzuBot) -> None:
    tree = _command_tree(full_bot)
    for path in HIDDEN_COMMANDS:
        assert path in tree, f"expected {path!r} in the command tree"
        assert _perms(tree[path]) == ADMIN, (
            f"{path!r} must carry default_member_permissions=ADMINISTRATOR"
        )


def test_user_facing_commands_stay_visible_and_unguarded(
    full_bot: CazzuBot,
) -> None:
    tree = _command_tree(full_bot)
    for path in USER_FACING:
        assert path in tree, f"expected {path!r} in the command tree"
        assert _perms(tree[path]) is hikari.UNDEFINED, (
            f"{path!r} must not be hidden"
        )
        assert _hooks(tree[path]) == [], (
            f"{path!r} must not carry a check hook"
        )


def test_every_command_is_hidden_checked_or_user_facing(
    full_bot: CazzuBot,
) -> None:
    """No command may exist that is neither hidden nor execution-checked.

    Hidden commands must additionally carry a permission-gate hook
    (defense in depth — Discord hides them, the hook still blocks
    execution), and a non-permission hook (cooldown, concurrency, …)
    never satisfies the gate.
    """
    tree = _command_tree(full_bot)
    for path, cmd in tree.items():
        if isinstance(cmd, (Group, SubGroup)):
            continue  # groups/subgroups are gated by their members
        hidden_top = path in HIDDEN_COMMANDS or (path[0],) in HIDDEN_GROUPS
        if hidden_top:
            assert _gates(cmd), (
                f"{path!r} is hidden but lacks a permission-gate hook"
            )
            continue
        if _gates(cmd):
            continue  # execution-checked (owner/admin/mod gate)
        assert path in USER_FACING, (
            f"{path!r} is neither hidden nor check-gated; add it to "
            "HIDDEN/USER_FACING or give it a guard hook"
        )
