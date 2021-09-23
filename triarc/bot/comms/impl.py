"""
Many definitions for communications-related
objects' implementation protocols.
"""

import datetime
import typing
from collections.abc import Iterable
from typing import Optional

from ..backend import Backend
from .base import CompositeContentInstance, Messageable

if typing.TYPE_CHECKING:
    from .base import CompositeContentInstance

ProxyType = typing.TypeVar("ProxyType", "ObjectProxy")


class ObjectProxy(typing.Protocol):
    """
    A base class for Backend high-level implementatino protocols.
    """

    def get_backend(self) -> "Backend":
        """Gets the Backend that implements this object."""
        ...

    def get_id(self) -> str:
        """
        Return an unique string identifier, determined by the
        backend implementation.

        Returns:
            str -- The unique identifier of this object.
        """
        ...

    def get_name(self) -> typing.Optional[str]:
        """
        May return a human-friendly name that describes this object.
        """
        ...


class UserProxy(ObjectProxy, typing.Protocol):
    """
    A high-level User implementation protocol.

    An User must be:
    * identifiable;
    * named;
    * messageable.

    Backends emit 'hi' and 'bye' events whenever an
    user logs in and logs out, respectively. The
    Bot class keeps track of known users, even after
    they log out, but doesn't record this information
    by default.
    """

    def as_messageable(self) -> Messageable:
        """
        Creates a target object from this user, as a Messageable-compliant
        object.
        """
        ...

    def is_self(self) -> bool:
        """
        Whether this user represents the Triarc bot itself in the backend
        platform.
        """
        ...

    def is_online(self) -> bool:
        """
        Whether this user is online.

        The result is always boiled down to being a 'yes' only if
        this user can be messaged in a way that the client at
        the other end of the wire will immediately receive it,
        possibly including the ability to react immediately.

        The reason this exists in spite of User.active is that it may
        be separate from how active backend objects are tracked by Bot.

        In IRC, there is no need for such distinction, however, some other
        platforms may not broadcast whenever a client becomes offline,
        requiring active polling, and thus in the meanwhile remaining 'active'
        (relevant) in the eyes of the Triarc bot as far as itself is concerned.

        TL;DR users are considered around till proven gone.
        """
        ...


class MessageProxy(ObjectProxy, typing.Protocol):
    """
    A high-level Message implementation protocol.

    Unlike old-school bot.Message, this implementation is
    more flexible and separates the concern of backend-specific
    representation from Triarc-relevant text content.
    """

    def origin_is_channel(self) -> bool:
        """
        Returns whether the origin of this message is a Channel.
        """
        ...

    def get_channel(self) -> Optional["ChannelProxy"]:
        """
        Returns the origin channel of this message, if applicable.
        """
        ...

    def quote_line(self) -> str:
        """
        Returns the 'quote line' of this message, in a single line of plaintext.

        The result should look something like, for instance, this:

            <AntonTheIRCGuy> I said some stuff! Hooray me!
        """
        ...

    def get_author(self) -> str:
        """
        Returns the author of this message, as an UserProxy's identifier string.
        """
        ...

    def is_composite(self) -> bool:
        """
        Returns whether the message is of a composite content kind.
        """
        ...

    def get_main_line(self) -> str:
        """
        Returns the main contents of this message in a single line.
        """
        ...

    def get_all_lines(self) -> Iterable[str]:
        """
        If the underlying Backend supports multi-line messages, returns
        several lines of text, one string per line. Otherwise, is
        equivalent to [get_main_line()].
        """
        ...

    def get_composite(self) -> Optional[CompositeContentInstance]:
        """
        If applicable, returns the composite content instance of this message.
        """
        ...

    def get_date(self) -> datetime.datetime:
        """
        Returns the date this message was sent at.
        """
        ...


class ChannelProxy(ObjectProxy, typing.Protocol):
    """
    A high-level Channel implementation protocol.

    Backends emit 'join' and 'part' events, which are
    picked up on by the base Backend class. Joined
    channels are indexed by the Bot class. A 'join'
    and 'part' events, respectively, *must* pass a
    ChannelProxy object, for which a Channel wrapper
    is created.
    """

    def as_messageble(self) -> Messageable:
        """
        Creates a target object from this channel, as a Messageable-compliant
        object.
        """
        ...

    def list_users(self) -> typing.Optional[typing.Generator[str, None, None]]:
        """
        Generates a list of users in this channel, by backend-specific user ID.

        """
