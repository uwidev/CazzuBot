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
        (["CazzuBot"], (False, False, False)),
        (["CazzuBot", "-d"], (True, False, False)),
        (["CazzuBot", "-p"], (False, True, False)),
        (["CazzuBot", "-s"], (False, False, True)),
    ],
)
def test_main_flags_reach_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: list[str],
    expected: tuple[bool, bool, bool],
) -> None:
    seen: dict[str, object] = {}

    def fake_load(
        *, debug: bool = False, production: bool = False, sandbox: bool = False
    ) -> Config:
        seen["load"] = (debug, production, sandbox)
        return Config(
            token="MTIzNDU2Nzg5MDEyMzQ1Ng.OTg3NjU0MzIxMDEyMzQ1Ng.dummy",
            owner_id=1,
            guild_id=2,
            db_path=str(tmp_path / "boot.db"),
            debug=debug,
            sandbox=sandbox,
        )

    def fake_run(self: object) -> None:
        seen["run"] = True

    monkeypatch.setattr(main_module.Config, "load", staticmethod(fake_load))
    monkeypatch.setattr(main_module.CazzuBot, "run", fake_run)
    monkeypatch.setattr(main_module, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", argv)

    main_module.main()

    assert seen == {"load": expected, "run": True}


def test_setup_logging_writes_file(tmp_path: Path) -> None:
    main_module.setup_logging(tmp_path)
    assert (tmp_path / "discord.log").exists()
