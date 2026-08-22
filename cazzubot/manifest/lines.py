"""Line-manifest machinery shared by the roles and channels parsers.

Both manifests are line-oriented (``[Header]`` sections, one item per
line, ``Name : token token`` syntax, ``OLD->NEW`` rename lines). The
reporting types, the raw-line split, the rename syntax, the rename
validations and the group-commit rule are identical across the two
domains; only the item specs, token parsers and name checks differ.
Keeping them here means the two parsers can't drift apart again.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any, TypeVar

from typing_extensions import override


@dataclass(frozen=True, slots=True)
class Issue:
    """One parse problem: line number plus human message."""

    line: int
    message: str

    @override
    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


class ManifestError(ValueError):
    """Raised when a manifest has any parse problems (all collected)."""

    def __init__(self, issues: list[Issue]) -> None:
        """Remember the collected ``issues``."""
        super().__init__(f"{len(issues)} manifest error(s)")
        self.issues = issues


def suggest(word: str, candidates: Iterable[str]) -> str:
    """A did-you-mean hint for an unknown word, or ``""``."""
    matches = difflib.get_close_matches(word, list(candidates), n=1)
    if not matches:
        return ""
    return f" — did you mean {matches[0]!r}?"


def rewrite_renames(
    text: str, renames: Sequence[tuple[int, str, str]]
) -> str:
    """Rewrite applied ``OLD->NEW`` lines to just ``NEW``.

    ``renames`` holds ``(line_no, old, new)`` for rename lines that were
    applied successfully. Everything else in the file is preserved byte
    for byte (comments, blank lines, tokens, the modeline). The arrow is
    matched with optional spaces around it — the parsers accept
    ``OLD -> NEW`` too, and a rewrite that missed that form would leave
    the manifest permanently re-seeing the rename as cleanup.
    """
    lines = text.splitlines(keepends=True)
    for line_no, old, new in renames:
        idx = line_no - 1
        if not (0 <= idx < len(lines)):
            continue
        lines[idx] = re.sub(
            rf"{re.escape(old)}\s*->\s*{re.escape(new)}",
            lambda _match: (
                new
            ),  # replacement is literal (backslashes safe)
            lines[idx],
            count=1,
        )
    return "".join(lines)


def split_name_line(
    raw: str, *, kind: str, line_no: int, issues: list[Issue]
) -> tuple[str, str]:
    """Split a raw item line into ``(name, token_part)``.

    Split on the raw line so leading/trailing whitespace in the name is
    still visible (``strip()`` would hide it); ``Name :`` with no tokens
    is a trailing separator, not a padded name.
    """
    if " : " in raw:
        name_part, _, token_part = raw.partition(" : ")
    elif raw.endswith(" :"):
        # ``Name :`` with no tokens — trailing separator
        name_part, token_part = raw[:-2], ""
    else:
        name_part, token_part = raw, ""
    raw_name = name_part
    name_part = name_part.strip()
    if name_part != raw_name:
        issues.append(
            Issue(
                line_no,
                f"{kind} name has leading/trailing whitespace — verbatim names can't round-trip",
            )
        )
    return name_part, token_part


def parse_rename(
    name_part: str,
    *,
    kind: str,
    line_no: int,
    issues: list[Issue],
) -> tuple[str, str | None] | None:
    """Extract ``(new_name, renamed_from)`` from an ``OLD->NEW`` line.

    Without a rename the name passes through unchanged (``renamed_from``
    is None). Malformed renames (missing old/new, no-op) are reported and
    yield None so the caller skips the line. The caller still validates
    the *new* name against its own round-trip rules.
    """
    if "->" not in name_part:
        return name_part, None
    old_part, _, new_part = name_part.partition("->")
    old, new = old_part.strip(), new_part.strip()
    if not old:
        issues.append(
            Issue(
                line_no,
                "rename has no old name before '->'",
            )
        )
        return None
    if not new:
        issues.append(
            Issue(
                line_no,
                "rename has no new name after '->'",
            )
        )
        return None
    if "->" in new:
        issues.append(
            Issue(
                line_no,
                f"rename target {new!r} contains '->' — renames can't chain",
            )
        )
        return None
    if old == new:
        issues.append(
            Issue(
                line_no,
                f"rename {old!r} -> {old!r} is a no-op",
            )
        )
        return None
    return new, old


def validate_renames(items: Iterable[Any], issues: list[Issue]) -> None:
    """No chains (A->B then B->C) and no duplicate rename sources.

    ``items`` are spec objects with ``name`` / ``renamed_from`` / ``line``
    attributes (duck-typed: works for role and channel specs alike).
    """
    rename_by_old: dict[str, Any] = {}
    for item in items:
        if item.renamed_from is None:
            continue
        if item.renamed_from in rename_by_old:
            issues.append(
                Issue(
                    item.line,
                    f"duplicate rename source {item.renamed_from!r} "
                    f"(first renamed at line {rename_by_old[item.renamed_from].line})",
                )
            )
            continue
        rename_by_old[item.renamed_from] = item
    for old, item in rename_by_old.items():
        if item.name in rename_by_old:
            issues.append(
                Issue(
                    item.line,
                    f"rename chain not supported: {old!r} -> {item.name!r} is itself renamed elsewhere",
                )
            )


GroupT = TypeVar("GroupT")
ItemT = TypeVar("ItemT")


def commit_group(
    group: GroupT | None,
    items: list[ItemT],
    groups: list[GroupT],
    seen_titles: dict[str, int],
    issues: list[Issue],
    *,
    group_word: str,
    items_field: str,
) -> None:
    """Commit an in-progress group, reporting duplicate titles.

    ``group_word`` is the human word for the section ("group" /
    "category"); ``items_field`` is the spec's member field ("roles" /
    "channels"). A titled group commits only once; an implicit
    (header-less) group commits only when it has items.
    """
    if group is None:
        return
    if group.title is not None and group.title in seen_titles:
        issues.append(
            Issue(
                group.line,
                f"duplicate {group_word} {group.title!r} "
                f"(first at line {seen_titles[group.title]})",
            )
        )
    elif group.title is not None:
        seen_titles[group.title] = group.line
        groups.append(replace(group, **{items_field: tuple(items)}))
    elif items:
        # implicit group — commit only if it has items
        groups.append(replace(group, **{items_field: tuple(items)}))
