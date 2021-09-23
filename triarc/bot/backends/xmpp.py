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

from ..backend import ThrottledBackend
from ..bot import MessageLegacy
from ..comms.base import Messageable
from ..comms.impl import (ChannelProxy, Messageable, MessageProxy, UserProxy,
                          datetime)

if typing.TYPE_CHECKING:
    from ..backend import Backend


@attr.s(auto_attribs=True)
class XMPPAddress(Messageable):
    """A messageable XMPP address."""

    pass


@attr.s(auto_attribs=True)
class XMPPChannel(ChannelProxy):
    """A XMPP MUC."""

    pass


@attr.s(auto_attribs=True)
class XMPPUser(UserProxy):
    """An XMPP user."""

    pass


@attr.s(auto_attribs=True)
class XMPPMessage(MessageProxy):
    """A message received from XMPP."""

    pass


@attr.s(auto_attribs=True)
class XMPPBackend(ThrottledBackend):
    """The XMPP backend object."""

    pass
