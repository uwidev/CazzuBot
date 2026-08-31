"""Frog statuses — unique status classes owning their values.

The status class IS the identity (``Status.key`` = the contribution
``source``); the store records only provenance. Sibling reaction statuses
(Pog/Froggers) stay separate rows so expiry of the winner falls back to
the next — the fold in ``reactions.py`` picks by priority.

The frog modules are resolved at call time (``tests/plugins/frogs/_current.py``):
the plugin-reload tests purge and re-import ``plugins.frogs.*`` mid-suite,
so collection-time references would go stale against the registry.
"""

from __future__ import annotations

import pendulum
import pytest

from cazzubot.bot import CazzuBot
from cazzubot.statuses import Scope, status_by_source

from plugins.frogs.seams import FrogSeam

from tests.plugins.frogs._current import statuses
from tests.fakes import FakeMember, rest_of

_CLASSY_ROLE_DEV = 1542294599358353430
_CLASSY_ROLE_PROD = 1542293782588952696


def test_frog_statuses_registered_by_source() -> None:
    """Module import registers each status under its key (reload-safe)."""
    st = statuses()
    st.register_frog_statuses()  # idempotent re-register
    assert status_by_source("frog:blessing:pog") is st.POG_REACTION
    assert (
        status_by_source("frog:blessing:froggers") is st.FROGGERS_REACTION
    )
    assert status_by_source("frog:blessing:classy") is st.CLASSY_ROLE
    assert status_by_source("nope") is None


def test_reaction_describe_reads_class_values() -> None:
    st = statuses()
    assert st.POG_REACTION.describe() == (
        "For 1 hour, a **1%** chance the bot reacts to your messages "
        + "with the froggers emoji (10s cooldown)."
    )
    assert st.FROGGERS_REACTION.describe() == (
        "For 1 hour, a **7%** chance the bot reacts to your messages "
        + "with the froggers emoji (10s cooldown)."
    )


def test_role_describe_reads_class_values() -> None:
    assert (
        statuses().CLASSY_ROLE.describe()
        == "Grants the **Classy** role for 3 hours."
    )


def test_role_status_resolves_guild_role() -> None:
    st = statuses()
    assert st.CLASSY_ROLE.role_id_for("development") == _CLASSY_ROLE_DEV
    assert st.CLASSY_ROLE.role_id_for("production") == _CLASSY_ROLE_PROD


def test_classy_role_ids_is_the_bound_set() -> None:
    ids = statuses().classy_role_ids()
    assert ids == frozenset({_CLASSY_ROLE_DEV, _CLASSY_ROLE_PROD})


async def test_reaction_statuses_are_separate_rows(
    full_bot: CazzuBot,
) -> None:
    """Pog and Froggers publish separate rows (sibling statuses, not merged)."""
    bot = full_bot
    st = statuses()
    now = pendulum.now("UTC")
    await st.POG_REACTION.apply(
        bot,
        scope=Scope.member(1),
        provenance="frog:pog:normal",
        now=now,
    )
    await st.FROGGERS_REACTION.apply(
        bot,
        scope=Scope.member(1),
        provenance="frog:froggers:normal",
        now=now,
    )
    rows = await bot.statuses.list(
        Scope.member(1), FrogSeam.FROG_REACTION, now=now
    )
    assert {r.source for r in rows} == {
        "frog:blessing:pog",
        "frog:blessing:froggers",
    }


async def test_reaction_apply_provenance_only(full_bot: CazzuBot) -> None:
    """apply() stores only provenance; the chance lives on the class."""
    bot = full_bot
    st = statuses()
    await st.POG_REACTION.apply(
        bot, scope=Scope.member(2), provenance="frog:pog:normal"
    )
    rows = await bot.statuses.list(Scope.member(2), FrogSeam.FROG_REACTION)
    assert rows and rows[0].source == "frog:blessing:pog"
    assert rows[0].payload == {"from": "frog:pog:normal"}
    # the chance is read off the class, never the row
    klass = status_by_source(rows[0].source)
    assert isinstance(klass, st.ReactionStatus)
    assert klass.chance == 0.01


async def test_classy_role_apply_publishes_and_converges(
    full_bot: CazzuBot,
) -> None:
    """Classy apply publishes the role seam and the converger grants the role."""
    bot = full_bot
    st = statuses()
    converger = st.RoleConverger(st.classy_role_ids())
    bot.statuses.register_converger(FrogSeam.CLASSY_ROLE, converger)
    rest = rest_of(bot)
    target = FakeMember(id=123, name="tester")
    rest.members[(bot.config.guild_id, 123)] = target

    await st.CLASSY_ROLE.apply(
        bot,
        scope=Scope.member(123),
        provenance="frog:classy:normal",
    )
    contribs = await bot.statuses.list(
        Scope.member(123), FrogSeam.CLASSY_ROLE
    )
    assert contribs and contribs[0].source == "frog:blessing:classy"
    assert contribs[0].payload == {"from": "frog:classy:normal"}
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert _CLASSY_ROLE_DEV in member.role_ids
    assert rest.added_roles == [
        (123, _CLASSY_ROLE_DEV, "classy frog role status")
    ]


async def test_role_converger_removes_role_on_expiry(
    full_bot: CazzuBot,
) -> None:
    """After the contribution expires, converging reverts (idempotent)."""
    bot = full_bot
    st = statuses()
    converger = st.RoleConverger(st.classy_role_ids())
    bot.statuses.register_converger(FrogSeam.CLASSY_ROLE, converger)
    rest = rest_of(bot)
    target = FakeMember(id=123, name="tester")
    rest.members[(bot.config.guild_id, 123)] = target

    now = pendulum.now("UTC")
    await st.CLASSY_ROLE.apply(
        bot,
        scope=Scope.member(123),
        provenance="frog:classy:normal",
        now=now,
    )
    # past the 3h window: the row reads as absent and is pruned
    assert (
        await bot.statuses.list(
            Scope.member(123),
            FrogSeam.CLASSY_ROLE,
            now=now.add(hours=4),
        )
        == []
    )
    await converger(bot, Scope.member(123), FrogSeam.CLASSY_ROLE.key)
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert member.role_ids == set()
    assert rest.removed_roles == [
        (123, _CLASSY_ROLE_DEV, "classy frog role status")
    ]


async def test_role_converger_only_removes_known_roles(
    full_bot: CazzuBot,
) -> None:
    """A foreign role on the member is never touched by the converger."""
    from tests.fakes import FakeRole

    bot = full_bot
    st = statuses()
    converger = st.RoleConverger(st.classy_role_ids())
    bot.statuses.register_converger(FrogSeam.CLASSY_ROLE, converger)
    rest = rest_of(bot)
    foreign = FakeRole(id=987654, name="some other role")
    target = FakeMember(id=123, name="tester", roles=[foreign])
    rest.members[(bot.config.guild_id, 123)] = target

    await st.CLASSY_ROLE.apply(
        bot,
        scope=Scope.member(123),
        provenance="frog:classy:normal",
    )
    await converger(bot, Scope.member(123), FrogSeam.CLASSY_ROLE.key)
    member = await bot.rest.fetch_member(bot.config.guild_id, 123)
    assert member.role_ids == {_CLASSY_ROLE_DEV, 987654}


@pytest.mark.parametrize(
    "key", ["frog:blessing:pog", "frog:blessing:froggers"]
)
async def test_reaction_status_is_member_scoped(
    full_bot: CazzuBot, key: str
) -> None:
    """A member-scoped reaction status refuses a guild scope."""
    st = statuses()
    klass = status_by_source(key)
    assert isinstance(klass, st.ReactionStatus)
    with pytest.raises(TypeError, match="member-scoped"):
        await klass.apply(full_bot, scope=Scope.guild(1), provenance="p")


def test_status_classes_are_distinct_types() -> None:
    st = statuses()
    assert isinstance(st.POG_REACTION, st.ReactionStatus)
    assert isinstance(st.CLASSY_ROLE, st.RoleStatus)
    assert not isinstance(st.POG_REACTION, st.RoleStatus)
    assert not isinstance(st.CLASSY_ROLE, st.ReactionStatus)
