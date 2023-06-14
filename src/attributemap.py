"""A mapping that stores items onto its attributes.

Created to allow encoding and decoding onto the TinyDB database. Entries to the database
should be in the form of this class.
"""

from collections.abc import Mapping, MutableMapping
from typing import Any, Iterator, TypeVar


KT = TypeVar("KT")
VT = TypeVar("VT")


class AttributeMap(MutableMapping[KT, VT]):
    """Mappings are stored as attributes for easier type-hinting and autocomplete."""

    def __init__(self, data: Mapping[KT, VT] = {}) -> None:
        self.__dict__ = dict(data)

    def __getitem__(self, key: KT) -> VT:
        return self.__dict__[key]

    def __setitem__(self, key: KT, value: VT):
        self.__dict__[key] = value

    def __delitem__(self, key: Any) -> None:
        del self.__dict__[key]

    def __iter__(self) -> Iterator:
        return iter(self.__dict__)

    def __len__(self) -> int:
        return len(self.__dict__)
