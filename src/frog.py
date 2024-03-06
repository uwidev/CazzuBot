"""Helper functions for ext.frog."""

import discord


def formatter(
    s: str, *, member: discord.Member, frog_old: int = None, frog_new: int = None
):
    """Format string with rank-related placeholders.

    {avatar}
    {name} -> display_name
    {mention}
    {id}
    {frog_old} -> previous frog
    {frog_new} -> new/total frog
    """
    return s.format(
        avatar=member.avatar.url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        frog_old=frog_old,
        frog_new=frog_new,
    )
