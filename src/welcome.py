"""Public helper functions for welcome extension."""

import discord


def formatter(s: str, *, member: discord.Member):
    """Format a string with member-related placeholders.

    Available placeholders are as follows.
    {avatar}
    {name} -> display_name
    {mention}
    {id}
    """
    # member = kwargs.get("member")
    return s.format(
        avatar=member.avatar.url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
    )
