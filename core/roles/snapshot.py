"""The role-snapshot shape shared by the engine and the live executor."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class RoleSnapshot(TypedDict):
    """One guild role as plain data.

    ``position`` is a top-down sidebar index (0 = highest role). Older
    exports may omit ``icon``.
    """

    position: int
    id: str
    name: str
    color: str | None
    hoisted: bool
    mentionable: bool
    managed: bool
    permissions: list[str]
    icon: NotRequired[str | None]
    tags: NotRequired[list[str]]
