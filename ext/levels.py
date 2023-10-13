"""Contains the impplementation of levels systems.

A user's level is derived from a user's experience points. Because of this, levels do
not actually need to be stored internally.
"""

import logging
from enum import Enum, auto
from math import cos, pi

import discord

from src import levels_helper
