"""Config.load — the --bot/--guild sides select token and guild."""

from __future__ import annotations

import pytest

from cazzubot.config import GUILD_ID_DEV, GUILD_ID_PROD, Config, parse_side

_TOKEN_PROD = "MTIzNDU2Nzg5MDEyMzQ1Ng.OTg3NjU0MzIxMDEyMzQ1Ng.PROD"
_TOKEN_DEV = "MTIzNDU2Nzg5MDEyMzQ1Ng.OTg3NjU0MzIxMDEyMzQ1Ng.DEV"
_GID_PROD = "293796316193095690"
_GID_DEV = "408801760581386245"


@pytest.fixture(autouse=True)
def _no_dotenv(  # pyright: ignore[reportUnusedFunction] pytest autouse fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never load the real .env — it would refill deleted vars."""
    monkeypatch.setattr("cazzubot.config.load_dotenv", lambda: False)


def _env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    token: str | None = _TOKEN_PROD,
    token_dev: str | None = _TOKEN_DEV,
    owner: str | None = "1",
    gid_prod: str | None = _GID_PROD,
    gid_dev: str | None = _GID_DEV,
) -> None:
    for name, value in (
        ("TOKEN", token),
        ("TOKEN_DEV", token_dev),
        ("OWNER_ID", owner),
        (GUILD_ID_PROD, gid_prod),
        (GUILD_ID_DEV, gid_dev),
    ):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    ("value", "side"),
    [
        ("production", "production"),
        ("p", "production"),
        ("P", "production"),
        ("develop", "development"),
        ("d", "development"),
        ("DEVELOP", "development"),
    ],
)
def test_parse_side(value: str, side: str) -> None:
    assert parse_side(value) == side


@pytest.mark.parametrize(
    "value", ["", "prod", "dev", "sandbox", "staging"]
)
def test_parse_side_rejects_unknown(value: str) -> None:
    with pytest.raises(ValueError):
        parse_side(value)


def test_load_defaults_to_develop_bot_and_guild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch)
    config = Config.load()
    assert config.token == _TOKEN_DEV
    assert config.guild_id == int(_GID_DEV)
    assert config.guild_kind == "development"


def test_load_bot_production_uses_prod_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch)
    config = Config.load(bot="production")
    assert config.token == _TOKEN_PROD


def test_load_guild_production_uses_prod_guild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch)
    config = Config.load(guild="production")
    assert config.guild_id == int(_GID_PROD)
    assert config.guild_kind == "production"


def test_load_db_path_follows_guild_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each guild side gets its own database file (dev/prod data apart)."""
    _env(monkeypatch)
    assert Config.load().db_path == "data/cazzubot-dev.db"
    assert Config.load(guild="production").db_path == "data/cazzubot-prod.db"
    # per-side env override wins
    monkeypatch.setenv("DB_PATH_DEV", "/tmp/dev.db")
    assert Config.load().db_path == "/tmp/dev.db"


def test_load_short_sides(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch)
    config = Config.load(bot="p", guild="d")
    assert config.token == _TOKEN_PROD
    assert config.guild_id == int(_GID_DEV)


def test_load_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, token=None, token_dev=None)
    with pytest.raises(RuntimeError, match="Missing discord token"):
        Config.load()


def test_load_missing_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, owner=None)
    with pytest.raises(RuntimeError, match="Missing OWNER_ID"):
        Config.load()


def test_load_missing_prod_guild_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, gid_prod=None)
    with pytest.raises(RuntimeError, match=GUILD_ID_PROD):
        Config.load(guild="production")


def test_load_missing_dev_guild_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _env(monkeypatch, gid_dev=None)
    with pytest.raises(RuntimeError, match=GUILD_ID_DEV):
        Config.load()


def test_load_ignores_legacy_guild_id_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GUILD_ID is gone — only GUILD_ID_PROD/GUILD_ID_DEV are read."""
    _env(monkeypatch, gid_prod=None, gid_dev=None)
    monkeypatch.setenv("GUILD_ID", "123456789012345678")
    with pytest.raises(RuntimeError, match=GUILD_ID_DEV):
        Config.load()
