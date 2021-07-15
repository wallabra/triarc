"""
Basic components at the core of Triarc's definition of messaging.
"""

import typing
from collections.abc import Iterable
from typing import Optional


class Messageable(typing.Protocol):
    """Any object to which messages can be sent."""

    async def message_line(self, line: str) -> bool:
        """Send a single line of plaintext."""
        ...

    async def message_lines(self, *lines: Iterable[str]) -> bool:
        """Send many lines of plaintext."""
        ...

    async def message_composite(self, instance: "CompositeContentInstance") -> bool:
        """Send a backend-specific composite message."""
        ...


class CompositeContentInstance(typing.Protocol):
    """
    An instance of composite content.

    Most details are handled by the Backend, except a listing of lines.
    """

    def get_lines(self) -> typing.Generator[str, None, None]:
        """
        Get all the plaintext lines constituing this CompositeContent.

        This will return plaintext even if the underlying composition isn't
        pure plaintext. In that case, simply extract the elements that are.
        """
        ...


class CompositeContentType(typing.Protocol):
    """
    An abstract composite content type.

    A Backend implementation may have multiple CompositeContent
    types. They must be returned in the get_composite_types() Backend method.
    """

    def construct_simple(
        self, *lines: Iterable[str]
    ) -> Optional[CompositeContentInstance]:
        """Construct from lines. Returns None if unsuccessful."""
        ...

    def construct_titled(
        self, header: str, *body: Iterable[str]
    ) -> Optional[CompositeContentInstance]:
        """Construct from a header line and body lines. Returns None if unsuccessful."""
        ...
