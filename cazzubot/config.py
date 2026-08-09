"""Runtime configuration, loaded from environment variables."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Plugins loaded by a bare ``-s``/``--sandbox`` (no names given).
SANDBOX_DEFAULT_PLUGINS: tuple[str, ...] = ("poll", "dev")


@dataclass(frozen=True)
class Config:
    """Everything the bot needs to boot.

    Loaded from environment variables (optionally via a ``.env`` file).

    - ``TOKEN`` / ``TOKEN_DEV``: discord bot token (dev used unless production)
    - ``OWNER_ID``: the bot owner's user id
    - ``GUILD_ID``: the one guild this bot serves
    - ``DB_PATH``: sqlite database file (default ``data/cazzubot.db``)
    """

    token: str
    owner_id: int
    guild_id: int
    db_path: str = "data/cazzubot.db"
    debug: bool = False
    sandbox_plugins: tuple[str, ...] | None = None
    debug_users: list[int] = field(default_factory=list)

    @property
    def sandbox(self) -> bool:
        """True in sandbox mode (a plugin allowlist was requested)."""
        return self.sandbox_plugins is not None

    @classmethod
    def load(
        cls,
        *,
        debug: bool = False,
        production: bool = False,
        sandbox: tuple[str, ...] | None = None,
    ) -> "Config":
        load_dotenv()

        owner_id = os.getenv("OWNER_ID")
        guild_id = os.getenv("GUILD_ID")
        token = os.getenv("TOKEN" if production else "TOKEN_DEV")

        if token is None:
            raise RuntimeError(
                "Missing discord token: set TOKEN_DEV (dev) or TOKEN "
                + "(production) in .env"
            )
        if owner_id is None:
            raise RuntimeError("Missing OWNER_ID in .env")
        if guild_id is None:
            raise RuntimeError(
                "Missing GUILD_ID in .env — this bot serves one guild"
            )

        return cls(
            token=token,
            owner_id=int(owner_id),
            guild_id=int(guild_id),
            db_path=os.getenv("DB_PATH", "data/cazzubot.db"),
            debug=debug,
            sandbox_plugins=sandbox,
            debug_users=[
                int(uid)
                for uid in os.getenv("DEBUG_USERS", "").split(",")
                if uid.strip()
            ],
        )
