"""Single-entry admin CLI.

    python -m cazzubot.cli <domain> <verb> [options]
    cazzubot-cli <domain> <verb> [options]        # console-script alias

Domains: roles (live manifest management), snapshot (live fetch),
manifest (offline render/lint). New domains are one module under
``cazzubot/cli/`` exposing a :class:`~cazzubot.cli.core.Domain`.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import cast

from cazzubot.cli import channels, manifest, roles, snapshot
from cazzubot.cli.core import Domain, LiveHandler, with_client

DOMAINS: dict[str, Domain] = {
    roles.domain.name: roles.domain,
    snapshot.domain.name: snapshot.domain,
    manifest.domain.name: manifest.domain,
    channels.domain.name: channels.domain,
}


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the requested domain verb."""
    args = build_parser().parse_args(argv)
    command = DOMAINS[args.domain].commands[args.verb]
    if command.live:
        handler = cast(LiveHandler, command.handler)
        return asyncio.run(with_client(handler, args))
    return asyncio.run(command.handler(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cazzubot-cli",
        description="Single entry for CazzuBot admin tooling.",
    )
    sub = parser.add_subparsers(dest="domain", required=True)

    for name, domain in DOMAINS.items():
        common = argparse.ArgumentParser(add_help=False)
        common.add_argument(
            "--bot",
            default="develop",
            choices=("production", "p", "develop", "d"),
            help="which bot to run: production (TOKEN) or develop (TOKEN_DEV)",
        )
        common.add_argument(
            "--guild",
            default="develop",
            choices=("production", "p", "develop", "d"),
            help="which guild to target: production or development",
        )
        for add_group in domain.common_args:
            add_group(common)
        domain_parser = sub.add_parser(name, help=domain.help)
        verbs = domain_parser.add_subparsers(dest="verb", required=True)
        for verb, command in domain.commands.items():
            verb_parser = verbs.add_parser(
                verb, parents=[common], help=command.help
            )
            if command.add_args is not None:
                command.add_args(verb_parser)
    return parser
