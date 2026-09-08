"""Information-strategy enforcement — broadcast surfaces carry no magnitudes.

``docs/INFORMATION_STRATEGY.md`` governs what player-facing text may say
and where. This test makes the **broadcast** half of that policy
mechanical, the way ``tests/core/test_csr_boundary.py`` makes an
architectural rule mechanical: a string a member reads *without asking*
must stay free of the tunable magnitudes R5 bans.

Checked surfaces (the ones a machine can find):

 - the slash picker for the member-facing commands — command descriptions,
   option descriptions and the description of the group that holds them
   (``USER_FACING`` in ``test_command_guards`` is the authority for which
   commands those are, so this sweep and the security sweep cannot drift)
 - the footer tip sets plugins declare (``Plugin.tip_sets``)
 - the announcement drafts under ``docs/announcements/``

Deliberately NOT checked — exactness is the point there: opt-in item
cards, the commitment dialogs, and staff surfaces (R10). The surface map
in the strategy doc is the full classification.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.bot import CazzuBot
from core.tips import TIP_SETS
from lightbulb.commands.commands import CommandBase
from lightbulb.commands.groups import Group, SubGroup

from tests.core.test_command_guards import USER_FACING

# The banned broadcast patterns, one per R5 knob: a chance (percent sign),
# an exp magnitude (a digit beside "exp"), a rarity tier (the tier list
# words) and a spawn weight. Labels are what the assertion reports.
_BANNED: tuple[tuple[str, str], ...] = (
    ("percent sign", r"%"),
    ("exp magnitude", r"\b\d+\s*exp\b|\bexp\w*\s*\d+\b"),
    ("rarity tier", r"\b(?:common|uncommon|rare|special)\b"),
    ("weight", r"\bweights?\b"),
)

_BANNED_PATTERNS = tuple(
    (label, re.compile(pattern, re.I)) for label, pattern in _BANNED
)

_ANNOUNCEMENTS = Path("docs/announcements")

# the collector's floor — a sweep that silently sees nothing always passes
# (the member-facing picker + tips + announcement drafts collect 30+ today)
_MIN_SURFACES = 25


def _banned(text: str) -> list[str]:
    """The labels of every banned broadcast pattern ``text`` carries."""
    return [
        label
        for label, pattern in _BANNED_PATTERNS
        if pattern.search(text)
    ]


def _command_tree(
    bot: CazzuBot,
) -> dict[tuple[str, ...], Group | SubGroup | type[CommandBase]]:
    """path -> command class or group (mirrors ``test_command_guards``)."""
    tree: dict[tuple[str, ...], Group | SubGroup | type[CommandBase]] = {}
    for mapping in bot.lightbulb.invokable_commands.values():
        for path, collection in mapping.items():
            if collection.slash is not None:
                tree[path] = collection.slash
    return tree


def _picker_strings(bot: CazzuBot) -> list[tuple[str, str]]:
    """(origin, text) for every string in the member-facing `/` picker."""
    tree = _command_tree(bot)
    found: list[tuple[str, str]] = []
    for path in sorted(USER_FACING):
        cmd = tree.get(path)
        assert cmd is not None, f"{path!r} missing from the command tree"
        data = cmd._command_data  # pyright: ignore[reportPrivateUsage]
        label = "/".join(path)
        found.append((f"{label} description", data.description))
        for name, option in data.options.items():
            found.append((f"{label} option {name}", option.description))
        # the holding group's own picker line — members see it too
        parent = tree.get(path[:-1])
        if isinstance(parent, (Group, SubGroup)):
            found.append(
                (f"{path[0]} group description", parent.description)
            )
    return found


def _tip_strings() -> list[tuple[str, str]]:
    """(origin, text) for every registered footer tip."""
    return [
        (f"tip {context}", tip)
        for context, tips in sorted(TIP_SETS.items())
        for tip in tips
    ]


def _announcement_strings() -> list[tuple[str, str]]:
    """(origin, text) for every announcement draft (whole file)."""
    return [
        (str(path), path.read_text())
        for path in sorted(_ANNOUNCEMENTS.rglob("*.md"))
    ]


def test_broadcast_surfaces_carry_no_banned_patterns(
    full_bot: CazzuBot,
) -> None:
    """No broadcast string may carry odds, exp values, tiers or weights."""
    surfaces = (
        _picker_strings(full_bot)
        + _tip_strings()
        + _announcement_strings()
    )
    assert len(surfaces) >= _MIN_SURFACES, (
        f"only {len(surfaces)} broadcast strings collected — the sweep is "
        "not seeing the surfaces it claims to check"
    )
    offenders = [
        (origin, text, _banned(text))
        for origin, text in surfaces
        if _banned(text)
    ]
    assert offenders == [], (
        "broadcast surfaces must stay unquantified:\n"
        + (
            "\n".join(
                f"  {origin}: {labels} in {text!r}"
                for origin, text, labels in offenders
            )
        )
    )


def test_thaw_command_description_is_dequantified(
    full_bot: CazzuBot,
) -> None:
    """The thaw picker line states the kind, not the odds (broadcast, R5)."""
    picker = dict(_picker_strings(full_bot))
    text = picker["inventory/thaw description"]
    assert _banned(text) == []
    assert "remains" in text.lower()  # R1 — kind stays concrete


def test_staff_surfaces_are_not_swept(full_bot: CazzuBot) -> None:
    """R10 — the sweep only sees member-facing commands.

    ``/calc to`` states a raw exp cost and is staff-only; it must not be
    in the broadcast set (and must not be exempted by hand).
    """
    origins = {origin for origin, _text in _picker_strings(full_bot)}
    assert not any(origin.startswith("calc") for origin in origins)
    assert "inventory/info description" in origins


@pytest.mark.parametrize(
    "text",
    [
        "Each thaw is a 50% gamble.",
        "Grants 20 exp when consumed.",
        "A rare frog with refined tastes.",
        "Drawn by spawn weight.",
    ],
)
def test_guard_flags_a_banned_fixture(text: str) -> None:
    """A guard that cannot fail is no guard — each pattern must fire."""
    assert _banned(text) != []


@pytest.mark.parametrize(
    "text",
    [
        (
            "Thaw a frozen frog: a per-unit gamble that may restore it or "
            "leave remains."
        ),
        "Check what a frog does with /inventory info <slot>!",
    ],
)
def test_guard_passes_clean_fixture(text: str) -> None:
    """Ordinal, magnitude-free copy is not a false positive."""
    assert _banned(text) == []
