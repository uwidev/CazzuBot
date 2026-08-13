"""CLI parser — the common --bot/--guild flags reach every verb."""

from __future__ import annotations

import pytest

from cazzubot.cli import build_parser


def test_common_flags_default_to_develop() -> None:
    args = build_parser().parse_args(["roles", "check"])
    assert args.bot == "develop"
    assert args.guild == "develop"


def test_common_flags_accept_both_sides() -> None:
    args = build_parser().parse_args(
        ["roles", "check", "--bot", "production", "--guild", "d"]
    )
    assert args.bot == "production"
    assert args.guild == "d"


def test_common_flags_reject_unknown_value() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["roles", "check", "--guild", "sandbox"])
