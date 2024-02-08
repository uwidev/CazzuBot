"""Defines encoding and decoding rules for custom datatypes.

Mainly used for trivializing user-defined Enums. Atomic data should be converted to
text, followed by ::ClassName. This can then later be referenced and converted
appropriately via the decoder's decoding_list.
"""

import json
import logging
from enum import Enum

from src.db.table import ModlogStatusEnum, ModlogTypeEnum


_log = logging.getLogger(__name__)


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        """Is called on every object, and serializes it to a string."""
        if isinstance(obj, Enum):
            return obj.value + "::" + obj.__class__.__name__

        return super().default(obj)


class CustomDecoder(json.JSONDecoder):
    decoding_list = (ModlogTypeEnum, ModlogStatusEnum)

    def __init__(self, *args, **kwargs):
        json.JSONDecoder.__init__(self, *args, object_hook=self.object_hook, **kwargs)

    def object_hook(self, data):
        """Is called on every dictionary object decoded from the json string."""
        for k, v in data.items():
            for enum_cls in self.decoding_list:
                if isinstance(v, str):
                    suffix = "::" + enum_cls.__name__
                    if v.endswith(suffix):
                        data[k] = enum_cls(v.removesuffix(suffix))
        return data


def dumps(obj):
    return json.dumps(obj, cls=CustomEncoder)


def loads(s):
    return json.loads(s, cls=CustomDecoder)
