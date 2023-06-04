# Helper functions
import logging

import discord
 
log = logging.getLogger('discord')
log.setLevel(logging.INFO)

class ReadOnlyDict(dict):
    # Safeguard to prevent writing to DB templates
    def __setitem__(self, key, value):
        raise TypeError('read-only dictionary, setting values is not supported')

    def __delitem__(self, key):
        raise TypeError('read-only dict, deleting values is not supported')