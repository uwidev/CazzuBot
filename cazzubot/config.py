"""Runtime configuration, loaded from environment variables."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Plugins loaded by a bare ``-s``/``--sandbox`` (no names given).
SANDBOX_DEFAULT_PLUGINS: tuple[str, ...] = ("poll", "dev")

# The two guilds this bot serves. Their ids live in .env (gitignored) so
# the real ids never land in the repository; the ``--guild`` flag picks
# which one is used. Common part front, side at the back.
GUILD_ID_PROD = "GUILD_ID_PROD"
GUILD_ID_DEV = "GUILD_ID_DEV"

# Accepted spellings for the ``--bot``/``--guild`` sides (case-insensitive).
_SIDES = {
    "production": ("production", "p"),
    "development": ("develop", "d"),
}


def parse_side(value: str) -> str:
    """Normalize a ``--bot``/``--guild`` value to 'production'/'development'.

    Accepts ``production``/``p`` and ``develop``/``d``, case-insensitive.
    Raises ``ValueError`` for anything else.
    """
    lowered = value.strip().lower()
    for side, aliases in _SIDES.items():
        if lowered in aliases:
            return side
    raise ValueError(
        f"side must be one of production|p|develop|d, got {value!r}"
    )


@dataclass(frozen=True)
class Config:
    """Everything the bot needs to boot.

    Loaded from environment variables (optionally via a ``.env`` file).
    The ``--bot``/``--guild`` sides select which token and guild are used;
    the guild ids themselves live in ``.env`` (``GUILD_ID_PROD`` /
    ``GUILD_ID_DEV``) so they stay out of the repository.

    - ``TOKEN`` / ``TOKEN_DEV``: discord bot token (dev unless production)
    - ``OWNER_ID``: the bot owner's user id
    - ``GUILD_ID_PROD`` / ``GUILD_ID_DEV``: the two guilds this bot serves
    - ``DB_PATH``: sqlite database file (default ``data/cazzubot.db``)
    """

    token: str
    owner_id: int
    guild_id: int
    db_path: str = "data/cazzubot.db"
    debug: bool = False
    sandbox_plugins: tuple[str, ...] | None = None
    debug_users: list[int] = field(default_factory=list)
    # the guild side this config was loaded with ('production'/'development');
    # direct constructions (tests) default to the development side
    guild_kind: str = "development"

    @property
    def sandbox(self) -> bool:
        """True in sandbox mode (a plugin allowlist was requested)."""
        return self.sandbox_plugins is not None

    @classmethod
    def load(
        cls,
        *,
        debug: bool = False,
        bot: str = "develop",
        guild: str = "develop",
        sandbox: tuple[str, ...] | None = None,
    ) -> "Config":
        load_dotenv()

        bot_side = parse_side(bot)
        guild_side = parse_side(guild)
        token = os.getenv(
            "TOKEN" if bot_side == "production" else "TOKEN_DEV"
        )
        owner_id = os.getenv("OWNER_ID")
        guild_var = (
            GUILD_ID_PROD if guild_side == "production" else GUILD_ID_DEV
        )
        guild_id = os.getenv(guild_var)

        if token is None:
            raise RuntimeError(
                "Missing discord token: set TOKEN_DEV (development) or "
                + "TOKEN (production) in .env"
            )
        if owner_id is None:
            raise RuntimeError("Missing OWNER_ID in .env")
        if guild_id is None:
            raise RuntimeError(
                f"Missing {guild_var} in .env — the {guild_side} guild id"
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
            guild_kind=guild_side,
        )
