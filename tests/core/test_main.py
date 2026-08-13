"""main.py wiring — the flags must reach Config and the bot must boot."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import main as main_module
from cazzubot import Config


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["CazzuBot"], (False, "develop", "develop", None)),
        (["CazzuBot", "-d"], (True, "develop", "develop", None)),
        (
            ["CazzuBot", "-b", "production"],
            (False, "production", "develop", None),
        ),
        (["CazzuBot", "-g", "d"], (False, "develop", "d", None)),
        (
            ["CazzuBot", "-b", "p", "-g", "production"],
            (False, "p", "production", None),
        ),
        (
            ["CazzuBot", "--bot", "develop", "--guild", "production"],
            (False, "develop", "production", None),
        ),
        (
            ["CazzuBot", "-s"],
            (False, "develop", "develop", ("poll", "dev")),
        ),
        (
            ["CazzuBot", "-s", "frogs"],
            (False, "develop", "develop", ("frogs",)),
        ),
        (
            ["CazzuBot", "-s", "frogs", "poll"],
            (False, "develop", "develop", ("frogs", "poll")),
        ),
        (
            ["CazzuBot", "-d", "-s", "frogs"],
            (True, "develop", "develop", ("frogs",)),
        ),
    ],
)
def test_main_flags_reach_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: list[str],
    expected: tuple[bool, str, str, tuple[str, ...] | None],
) -> None:
    seen: dict[str, object] = {}

    def fake_load(
        *,
        debug: bool = False,
        bot: str = "develop",
        guild: str = "develop",
        sandbox: tuple[str, ...] | None = None,
    ) -> Config:
        seen["load"] = (debug, bot, guild, sandbox)
        return Config(
            token="MTIzNDU2Nzg5MDEyMzQ1Ng.OTg3NjU0MzIxMDEyMzQ1Ng.dummy",
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "boot.db"),
            debug=debug,
            sandbox_plugins=sandbox,
        )

    def fake_run(self: object) -> None:
        seen["run"] = True

    monkeypatch.setattr(
        main_module.Config, "load", staticmethod(fake_load)
    )
    monkeypatch.setattr(main_module.CazzuBot, "run", fake_run)
    monkeypatch.setattr(main_module, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", argv)

    main_module.main()

    assert seen == {"load": expected, "run": True}


def test_setup_logging_writes_file(tmp_path: Path) -> None:
    main_module.setup_logging(tmp_path)
    assert (tmp_path / "discord.log").exists()
