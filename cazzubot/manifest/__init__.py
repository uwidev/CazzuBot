"""Shared machinery for the roles/channels manifest engines.

``lines`` holds the line-manifest parsing core both parsers share;
``plan`` / ``executor`` / ``cli`` (added by the sibling modules) hold the
plan ops, apply plumbing and CLI verbs the two domains have in common.
The domain-specific diffing and execution stay in ``cazzubot.roles`` and
``cazzubot.channels``.
"""
