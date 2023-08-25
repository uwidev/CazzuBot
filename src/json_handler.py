import json
import logging
from enum import Enum

from src.db_schema import ModlogStatusEnum, ModlogTypeEnum


_log = logging.getLogger(__name__)


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        _log.info("Encoding...")
        if isinstance(obj, Enum):
            _log.info("FOUND INSTANCE ENUM")
            return obj.value + "::" + obj.__class__.__name__

        return super().default(obj)


class CustomDecoder(json.JSONDecoder):
    conversion_list = (ModlogTypeEnum, ModlogStatusEnum)

    def __init__(self, *args, **kwargs):
        json.JSONDecoder.__init__(self, object_hook=self.object_hook, *args, **kwargs)

    def object_hook(self, data):
        for k, v in data.items():
            for enum_cls in self.conversion_list:
                if isinstance(v, str):
                    suffix = "::" + enum_cls.__name__
                    if v.endswith(suffix):
                        data[k] = enum_cls(v.removesuffix(suffix))
        return data
