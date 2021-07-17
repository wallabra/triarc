"""
The remote bot interface.

This is a type protocol for the remote Bot itself, including
several utilities expected to be available even via RPC.
"""

import typing
import attrs

if typing.TYPE_CHECKING:
    from .bot import Bot


class RemoteBot(typing.Protocol):
    """A remote interface for a Bot that exists either locally or remotely."""

    # async def get
    pass  # WIP
