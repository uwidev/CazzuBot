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

# Per-guild database files — the bot keeps development and production data
# apart (a development run must never touch production's rows, and a cloned
# production DB dropped in as the dev file keeps the clone isolated).
# Env var names (overridable, like GUILD_ID_PROD) + default file paths.
DB_PATH_PROD = "DB_PATH_PROD"
DB_PATH_DEV = "DB_PATH_DEV"
DB_PATH_DEFAULT_PROD = "data/cazzubot-prod.db"
DB_PATH_DEFAULT_DEV = "data/cazzubot-dev.db"

# The private channel per guild that hosts published asset blobs (the CDN
# sync uploads new/changed files here and stores the returned URLs).
# Common part front, side at the back, like GUILD_ID_*. Optional: without
# a channel the bot boots and skips the sync with a warning.
ASSET_CHANNEL_PROD = "ASSET_CHANNEL_PROD"
ASSET_CHANNEL_DEV = "ASSET_CHANNEL_DEV"

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


def _pick(side: str, prod: str, dev: str) -> str:
    """The production or development variant of a thing, by guild side."""
    return prod if side == "production" else dev


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
    - ``DB_PATH_PROD`` / ``DB_PATH_DEV``: per-guild sqlite database files
      (defaults ``data/cazzubot-prod.db`` / ``data/cazzubot-dev.db``)
    - ``ASSET_CHANNEL_PROD`` / ``ASSET_CHANNEL_DEV``: the private channel
      per guild that hosts published asset blobs (``None`` skips the CDN
      sync with a boot warning)
    """

    token: str
    owner_id: int
    guild_id: int
    db_path: str = "data/cazzubot.db"
    debug: bool = False
    sandbox_plugins: tuple[str, ...] | None = None
    debug_users: list[int] = field(default_factory=list)
    asset_channel_id: int | None = None
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
        token = os.getenv(_pick(bot_side, "TOKEN", "TOKEN_DEV"))
        owner_id = os.getenv("OWNER_ID")
        guild_var = _pick(guild_side, GUILD_ID_PROD, GUILD_ID_DEV)
        guild_id = os.getenv(guild_var)
        # one database per guild side (DB_PATH_* env overrides the default)
        db_var = _pick(guild_side, DB_PATH_PROD, DB_PATH_DEV)
        default_db = _pick(
            guild_side, DB_PATH_DEFAULT_PROD, DB_PATH_DEFAULT_DEV
        )
        # the asset channel follows the guild side too (optional)
        asset_var = _pick(
            guild_side, ASSET_CHANNEL_PROD, ASSET_CHANNEL_DEV
        )
        asset_channel = os.getenv(asset_var)

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
            db_path=os.getenv(db_var, default_db),
            debug=debug,
            sandbox_plugins=sandbox,
            debug_users=[
                int(uid)
                for uid in os.getenv("DEBUG_USERS", "").split(",")
                if uid.strip()
            ],
            asset_channel_id=int(asset_channel)
            if asset_channel and asset_channel.strip().isdigit()
            else None,
            guild_kind=guild_side,
        )
