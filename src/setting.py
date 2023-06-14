"""A abstraction of an entry for a the settings database."""
from collections.abc import Mapping
from typing import Any, Iterator, Union


class Setting(Mapping):
    def __init__(
        self,
        name: str,
        default: Union[str, int],
    ) -> None:
        self.name = name
        self.default = default

    def __getitem__(self, key: Any) -> Any:
        return self.__dict__[key]

    def __iter__(self) -> Iterator:
        return iter(self.__dict__)

    def __len__(self) -> int:
        return len(self.__dict__)
