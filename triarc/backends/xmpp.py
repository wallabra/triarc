"""
The XMPP backend.

Allows specifying a 'home' XMPP server, as well as an user
address and password. Interacts with all channels by default.
"""


from triarc.backend import DuplexBackend
from triarc.bot import Message


class XMPPMessage(Message):
    """A message received from XMPP."""

    pass


class XMPPBackend(DuplexBackend):
    """The XMPP backend object."""

    pass
