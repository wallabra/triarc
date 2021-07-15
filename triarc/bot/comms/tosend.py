"""
A 'draft' message yet to be sent.

May be composed of a single line, many lines, or complex content.
"""

import typing
from typing import Iterable

import attr

from .impl import CompositeContentInstance

if typing.TYPE_CHECKING:
    from .impl import Messageable

MTSType = typing.TypeVar("MTSType", "MessageToSend")


class MessageToSend(typing.Protocol):
    async def send(self) -> bool:
        """
        Attempts to send this MessageToSend.
        """
        ...

    def contents(self) -> typing.Generator[str, None, None]:
        """
        If applicable, reads the plaintext contents of this MessageToSend,
        line by line.
        """
        ...

    def target(self) -> "Messageable":
        """
        Gets the target Messageable that this MessageToSend refers to.
        """
        ...


@attr.s(autoattrib=True)
class PlaintextToSend:
    """A plaintext MessageToSend implementation."""

    target: "Messageable"
    lines: list[str]

    @classmethod
    def create_line(
        cls: typing.Type[MTSType], target: "Messageable", line: str
    ) -> MTSType:
        return cls(target, [line])

    @classmethod
    def create_lines(
        cls: typing.Type[MTSType], target: "Messageable", *lines: Iterable[str]
    ) -> MTSType:
        return cls(target, list(lines))

    async def send(self) -> bool:
        return await self.target.message_lines(self.lines)

    def target(self) -> "Messageable":
        return self.target

    def contents(self) -> typing.Generator[str, None, None]:
        yield from self.lines


class CompositeToSend:
    """A backend-specific composite message MessageToSend implementation."""

    target: "Messageable"
    instance: "CompositeContentInstance"

    @classmethod
    def create(
        cls: typing.Type[MTSType],
        target: "Messageable",
        composite: "CompositeContentInstance",
    ) -> MTSType:
        return cls(target, composite)

    async def send(self) -> bool:
        return await self.target.message_composite(self.instance)

    def target(self) -> "Messageable":
        return self.target

    def contents(self) -> typing.Generator[str, None, None]:
        yield from self.composite.get_lines()
