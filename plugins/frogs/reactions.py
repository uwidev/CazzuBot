"""Frog reactions — the message-time listener for FrogSeam.FROG_REACTION.

A user with an active reaction contribution (Pog/Froggers consumed) has
a per-message chance the bot reacts to their message with the froggers
emoji. The seam stores only provenance; the status **classes** own the
chance — this listener is the consumer:

- fold: each contribution's ``source`` maps back to its registered
  :class:`ReactionStatus`; the **highest-priority** live class decides the
  chance (ties → lowest source key). Sibling statuses stay separate rows,
  so expiry of the winner falls back to the next automatically.
- throttle: one reaction per user per ``_REACT_COOLDOWN`` seconds
  (10s per FROG.md). The cooldown is in-memory by design: a restart at
  worst allows one extra reaction; no table is worth that.
- gracefully no-ops while the froggers emoji asset is unpublished.
"""

from __future__ import annotations

import logging
import random
import time
from typing import cast

import hikari
import lightbulb

from cazzubot.bot import CazzuBot
from cazzubot.statuses import Scope, StatusContribution
from cazzubot.listeners import guild_listener

from .assets import FrogAsset
from .seams import FrogSeam
from .statuses import ReactionStatus, status_by_source

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

# seconds between reactions per user (FROG.md: "10 second cooldown per
# react") — also the practical Discord rate-limit guard.
_REACT_COOLDOWN = 10.0

# uid -> epoch of the last reaction; in-memory per D4.
_last_react: dict[int, float] = {}


@guild_listener(loader, hikari.MessageCreateEvent)
async def on_message(event: hikari.MessageCreateEvent) -> None:
    """Roll the reaction chance for the message author, throttled.

    Reads ``event.message`` (not the event's convenience props) so the
    offline fakes drive it exactly like the experience listener.
    """
    message = event.message
    author = message.author
    if author is None or not event.is_human:
        return
    bot = cast(CazzuBot, event.app)
    uid = author.id
    contribs = await bot.statuses.list(
        Scope.member(uid), FrogSeam.FROG_REACTION
    )
    best = _best_reaction(contribs)
    if best is None:
        return
    chance = best.chance  # from the class, never the row
    if chance <= 0.0 or random.random() >= chance:
        return
    if time.time() - _last_react.get(uid, 0.0) < _REACT_COOLDOWN:
        return
    emoji = await bot.assets.get(FrogAsset.FROG_FROGGERS)
    if emoji is None:
        return  # froggers emoji not published yet — nothing to react with
    try:
        await bot.rest.add_reaction(message.channel_id, message.id, emoji)
        _last_react[uid] = time.time()
    except hikari.NotFoundError:
        pass  # message or emoji vanished between pull and react — fine
    # hikari's REST client already sleeps through 429s internally, so a
    # rate-limited react cannot raise — there is no RateLimitError to catch


def _best_reaction(
    contribs: list[StatusContribution],
) -> ReactionStatus | None:
    """The highest-priority live reaction status (ties → lowest source key).

    Reads each contribution's ``source`` back to its registered class;
    unknown sources (a status removed from the registry) are skipped and
    eventually pruned at expiry.
    """
    statuses = [status_by_source(contrib.source) for contrib in contribs]
    reaction = [s for s in statuses if isinstance(s, ReactionStatus)]
    if not reaction:
        return None
    return max(
        reaction,
        key=lambda s: (s.priority, s.key),
    )
