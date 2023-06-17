"""A mapping that stores items onto its attributes.

Created to allow encoding and decoding onto the TinyDB database. Entries to the database
should be in the form of this class.
"""

from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any, TypeVar


KT = TypeVar("KT")
VT = TypeVar("VT")

BLACKLISTED_KEYS = [
    "clear",
    "copy",
    "fromkeys",
    "get",
    "items",
    "keys",
    "pop",
    "popitem",
    "setdefault",
    "to_dict",
    "update",
    "merge_update",
    "values",
    "mro",
]


class AttributeMap(MutableMapping[KT, VT]):
    """Writable TinyDB mapping.

    Intended to be used with @dataclass.

    Inherit from this whenever you want to write a class to the database. Only this type
    or Document should ever be written to the database, not dict. Has some handling of
    improper keys to stop collisions of useful dict functions.
    """

    def as_dict(self) -> dict:
        """Return a dict that mirrors this attribute map.

        Needs to do this recursively.
        """
        ret = {}
        for key, value in self.__dict__.items():
            if key == "_locked":  # bot.guild_defaults uses this key, ignore
                continue
            if isinstance(value, AttributeMap):
                ret[key] = value.as_dict()
            else:
                ret[key] = value

        return ret

    def __init__(self, data: Mapping[KT, VT] = None) -> None:
        if data is None:
            data = {}
        self.__dict__.update(data)
        super().__init__()

    def __getitem__(self, key: KT) -> VT:
        return self.__dict__[key]

    def __setitem__(self, key: KT, value: VT) -> None:
        if isinstance(key, str) and key in BLACKLISTED_KEYS:
            msg = f"Field {key} is blacklisted!"
            raise KeyError(msg)

        self.__dict__[key] = value

    def __setattr__(self, key: str, value: Any) -> None:
        self.__dict__[key] = value

    def __delitem__(self, key: Any) -> None:
        del self.__dict__[key]

    def __iter__(self) -> Iterator:
        return iter(self.__dict__)

    def __len__(self) -> int:
        return len(self.__dict__)

    def __repr__(self) -> str:
        return self._repr("AttributeMap")

    def _repr(self, name: str):
        inner = ", ".join(f"{key}={value!r}" for key, value in self.__dict__.items())
        return f"{name}({inner})"
