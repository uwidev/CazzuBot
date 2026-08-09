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
        (["CazzuBot"], (False, False, None)),
        (["CazzuBot", "-d"], (True, False, None)),
        (["CazzuBot", "-p"], (False, True, None)),
        (["CazzuBot", "-s"], (False, False, ("poll", "dev"))),
        (["CazzuBot", "-s", "frogs"], (False, False, ("frogs",))),
        (
            ["CazzuBot", "-s", "frogs", "poll"],
            (False, False, ("frogs", "poll")),
        ),
        (
            ["CazzuBot", "-d", "-s", "frogs"],
            (True, False, ("frogs",)),
        ),
    ],
)
def test_main_flags_reach_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: list[str],
    expected: tuple[bool, bool, tuple[str, ...] | None],
) -> None:
    seen: dict[str, object] = {}

    def fake_load(
        *,
        debug: bool = False,
        production: bool = False,
        sandbox: tuple[str, ...] | None = None,
    ) -> Config:
        seen["load"] = (debug, production, sandbox)
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
