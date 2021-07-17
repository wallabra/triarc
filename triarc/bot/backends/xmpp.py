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

from ..backend import DuplexBackend
from ..bot import MessageLegacy
from ..comms.impl import ChannelProxy, Messageable, UserProxy, MessageProxy, datetime
from ..comms.base import Messageable

if typing.TYPE_CHECKING:
    from ..backend import Backend


@attr.s(autoattrib=True)
class XMPPAddress(Messageable):
    """A messageable XMPP address."""

    pass


@attr.s(autoattrib=True)
class XMPPChannel(ChannelProxy):
    """A XMPP MUC."""

    pass


@attr.s(autoattrib=True)
class XMPPUser(UserProxy):
    """An XMPP user."""

    pass


@attr.s(autoattrib=True)
class XMPPMessage(MessageProxy):
    """A message received from XMPP."""

    pass


@attr.s(autoattrib=True)
class XMPPBackend(DuplexBackend):
    """The XMPP backend object."""

    pass
