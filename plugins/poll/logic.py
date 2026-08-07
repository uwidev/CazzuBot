"""Poll plugin — pure vote parsing and validation.

Comma-separated vote strings are parsed and checked against the poll's rules
(max votes, item range) without touching discord.
"""

from __future__ import annotations


def parse_votes(raw_input: str) -> list[int]:
    votes = [v.strip() for v in raw_input.split(",") if v]
    not_numbers = [
        v
        for v in votes
        if not (v.isdigit() or (v[0] == "-" and v[1:].isdigit()))
    ]
    if not_numbers:
        raise TypeError(f"Input is not a digit: {not_numbers}")
    if not votes:
        raise ValueError("No votes entered")
    return [int(v) for v in votes]


def validate_votes(
    votes: list[int], *, upper: int, max_vote: int
) -> list[str]:
    errors: list[str] = []
    out_of_range = [v for v in votes if v not in range(1, upper + 1)]
    if out_of_range:
        errors.append(f"Numbers out of range (1-{upper}): {out_of_range}")
    if len(votes) > max_vote:
        errors.append(f"Too many votes (max {max_vote}): got {len(votes)}")
    return errors
