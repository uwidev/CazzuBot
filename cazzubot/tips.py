"""Footer-tip registry — a plugin owns its tips, the core queries them.

Surfaces that want a cycling footer tip (the /frog view permit embed now;
/frog catalog and the /inventory views next) pull one string per render
via :func:`get_tip`. The *strings* do not live here: each plugin declares
its own sets in its ``Plugin.tip_sets`` (context key -> the tip strings
that surface cycles through), and ``bot.py`` registers them with this
registry at plugin load / unregisters at unload — the same lifecycle as
``bot.items`` / ``bot.assets``.

Copy is shared per context *within* the declaring plugin — both /frog
surfaces draw from the ``frog`` set, and the /inventory surfaces draw from
their own ``item`` set — so the strings stay close to the feature that
owns them instead of being baked into one central dict or any single embed
builder.

Tips name real slash commands (see plugins/inventory/extension.py): the
``item`` slots addressed by ``/inventory info`` / ``consume`` / ``thaw``.

Depends on: nothing (pure registry). Depended on by: ``bot`` (register /
unregister) and the ``frogs`` / ``inventory`` plugins (query on render).
"""

import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

# context key -> the tip strings that surface cycles through. This is a
# projection of the plugins' declarations: each loaded plugin's
# ``Plugin.tip_sets`` is folded in here at boot by ``bot.py``.
TIP_SETS: dict[str, tuple[str, ...]] = {}

# context key -> the plugin that registered it (for clean unregister).
_PROVIDER: dict[str, str] = {}


def register_tips(provider: str, sets: dict[str, tuple[str, ...]]) -> None:
    """Register ``provider``'s tip sets (context -> tip strings).

    Idempotent: re-registering replaces the entries, so a hot-reloaded
    plugin can resubmit. Contexts are owned by one provider each — a second
    provider registering the same context is a bug and is refused loudly.
    """
    for context, tips in sets.items():
        owner = _PROVIDER.get(context)
        if owner is not None and owner != provider:
            raise ValueError(
                f"tip context {context!r} already registered by {owner!r}"
            )
        TIP_SETS[context] = tuple(tips)
        _PROVIDER[context] = provider
    if sets:
        _log.info("registered %d tip set(s) for %s", len(sets), provider)


def unregister_tips(provider: str) -> None:
    """Drop every tip context the provider registered (its plugin unloaded)."""
    gone = [ctx for ctx, prov in _PROVIDER.items() if prov == provider]
    for ctx in gone:
        TIP_SETS.pop(ctx, None)
        _PROVIDER.pop(ctx, None)
    if gone:
        _log.info("unregistered %d tip set(s) for %s", len(gone), provider)


def get_tip(context: str) -> str:
    """One random tip string from ``context``'s registered set.

    Each render calls this fresh, so repeated renders cycle at random.
    An unregistered context is a caller bug — fail loudly.
    """
    tips = TIP_SETS.get(context)
    if tips is None:
        raise KeyError(f"no tip set registered for context {context!r}")
    return random.choice(tips)


class Tips:
    """The tips registry as a bot service (``bot.tips``).

    Owns nothing (tips are code, not tables). Wraps the module-level
    registry for consumers that hold the bot: register/unregister from
    plugin lifecycle, query one tip on embed render.
    """

    def __init__(self, bot: "CazzuBot") -> None:
        """Bind to ``bot`` (the registry is module-global)."""
        self.bot = bot

    def register(self, provider: str, sets: dict[str, tuple[str, ...]]) -> None:
        """Register the provider's tip sets."""
        register_tips(provider, sets)

    def unregister(self, provider: str) -> None:
        """Drop the provider's tip sets."""
        unregister_tips(provider)

    def get_tip(self, context: str) -> str:
        """One random tip from ``context``'s registered set."""
        return get_tip(context)