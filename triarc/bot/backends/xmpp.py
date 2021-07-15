"""
The XMPP backend.

Allows specifying a 'home' XMPP server, as well as an user
address and password. Interacts with all channels by default.
"""

# WIP


import typing
from typing import Iterable, List, Literal, Optional, Set

import attr
import trio

from triarc.backend import DuplexBackend
from triarc.bot import MessageLegacy

if typing.TYPE_CHECKING:
    from triarc.backend import Backend

    from ..comms.base import CompositeContentInstance
    from ..comms.impl import ChannelProxy, Messageable, UserProxy, datetime


class XMPPMessage(Message):
    """A message received from XMPP."""

    pass


class XMPPBackend(DuplexBackend):
    """The XMPP backend object."""

    pass
