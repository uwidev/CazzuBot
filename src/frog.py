"""Helper functions for ext.frog."""

import discord


def formatter(
	s: str,
	*,
	member: discord.Member,
	frog_cnt_old: int = None,
	frog_cnt_new: int = None,
	seasonal_cap_old: int = None,
	seasonal_cap_new: int = None,
):
	"""Format string with rank-related placeholders.

	{avatar}
	{name} -> display_name
	{mention}
	{id}
	{frog_cnt_old} -> previous total frog
	{frog_cnt_new} -> new/total total frog
	{seasonal_cap_old} -> captured season old
	{seasonal_cap_new} -> capture season new
	"""
	return s.format(
		avatar=member.avatar.url,
		name=member.display_name,
		mention=member.mention,
		id=member.id,
		frog_cnt_old=frog_cnt_old,
		frog_cnt_new=frog_cnt_new,
		seasonal_cap_old=seasonal_cap_old,
		seasonal_cap_new=seasonal_cap_new,
	)
