"""
Many definitions for communications-related
objects' high-level wrappers.
"""

import datetime
import hashlib
import typing
import uuid
from collections.abc import Iterable
from typing import Any, Optional

import attr

from ..backend import Backend
from ..bot import Bot

if typing.TYPE_CHECKING:
    from .impl import ChannelProxy, MessageProxy, ProxyType, UserProxy
    from .base import CompositeContentInstance


BackendObjectType = typing.TypeVar("BackendObjectType", "BackendObject")


@attr.s(auto_attribs=True)
class BackendObject(typing.Generic[ProxyType]):
    """
    A base class for common code to assist with Backend abstraction.

    Every BackendObject must have an unique string identifier, and may
    have a human-friendly name, and also has an UUID, which by default is
    random and runtime-ephemeral.
    """

    # The Bot.
    bot: "Bot"

    # The underlying backend object implementation.
    proxy: ProxyType

    # The origin Backend.
    backend: Backend

    # The object's unique identifier string.
    identifier: str

    # The object's runtime UUID.
    unique: uuid.UUID = attr.Factory(lambda x: x if x is not None else uuid.uuid4())

    # Whether this object is active in the context of this Bot.
    #
    # The exact definition varies: for Users, it usually means whether they
    # are online; for Channels, it usually means whether the bot's respective
    # user is joined to it.
    #
    # If not applicable, e.g. for a Message, None suffices.
    active: Optional[bool] = None

    @classmethod
    def create(
        cls: typing.Type[BackendObjectType],
        bot: "Bot",
        proxy: ProxyType,
        active: Optional[bool] = None,
        unique: Optional[uuid.UUID] = None,
    ) -> BackendObjectType:
        """
        Initializes a wrapper around a Backend object.
        For internal use only.

        Arguments:
            bot {Bot} -- The Bot to whom the backend pertains.
            proxy {ObjectProxy} -- The underlying backend object.
            unique {Optional[uuid.UUID]} -- If desired, a custom UUID.

        Returns:
            T -- The wrapper object :)
        """
        return cls(bot, proxy, proxy.get_backend(), proxy.get_id(), unique)

    @property
    def name(self) -> typing.Optional[str]:
        """The human-friendly name of this object."""
        return self.proxy.get_name()


@attr.s(auto_attribs=True)
class Channel(BackendObject[ChannelProxy]):
    """
    A high-level wrapper class for backends' channel objects.

    A channel is defined as a space where any amount of Users may be
    subscribed to, an association upon which both sending and receiving
    messages is possible for the Users involved, although sent messages
    being received by other Users is not guaranteed.

    While many platforms distinguish the ability to send messages to
    and receive messages from an user as a special, two-user type of
    channel, Triarc does not make this distinction.
    """

    def list_users(self) -> typing.Generator["User", None, None]:
        """
        Iterates on all User objects in this Channel.
        """
        for user_id in self.proxy.list_users():
            user = self.bot.find_user(user_id)

            if user is not None:
                yield user

    async def message_line(self, line: str) -> bool:
        """Send a single line of plaintext to this Channel."""
        return await self.proxy.post_message(line)

    async def message_lines(self, *lines: Iterable[str]) -> bool:
        """Send many lines of plaintext to this Channel."""
        return await self.proxy.post_message_lines(*lines)


@attr.s(auto_attribs=True)
class User(BackendObject[UserProxy]):
    """A high-level user wrapper class."""

    async def message_line(self, line: str) -> bool:
        """Send a single line of plaintext to this Channel."""
        return await self.proxy.send_message(line)

    async def message_lines(self, *lines: Iterable[str]) -> bool:
        """Send many lines of plaintext to this Channel."""
        return await self.proxy.send_message_lines(*lines)

    async def is_online(self) -> bool:
        """
        Whether this user is online.

        Automatically updates self.active.
        """
        res = self.proxy.is_online()
        self.active = res

        return res


@attr.s(auto_attribs=True)
class Message(BackendObject[MessageProxy]):
    """A high-level message wrapper class."""

    # The origin channel
    channel: Channel

    def prepare_lines(self, lines: list[str], quote: bool = False) -> "Message":
        """Prepare a message, including handling quotation."""
        if quote:
            lines.insert(0, self.proxy.quote_line())

        new_message = self.bot.wrap_message(
            self.backend.construct_message_lines(self.channel.identifier, lines)
        )

        return new_message

    async def reply_simple_public(
        self, *lines: Iterable[str], quote: bool = False
    ) -> bool:
        """
        Replies publicly to this message, with a 'simple' (plaintext-only)
        message.
        """
        if not self.proxy.origin_is_channel():
            return await self.reply_simple_private(*lines, quote=quote)

        lines = self.quote_lines(list(lines), quote=quote)

        self.channel

    async def reply_simple_private(
        self, *lines: Iterable[str], quote: bool = False
    ) -> bool:
        lines = self.quote_lines(list(lines), quote=quote)


class MessageLegacyInterface(typing.Protocol):
    """
    Specifies the legacy Message interface, pre-0.3.0.
    """

    backend: Backend
    line: str
    author_name: str
    author_addr: str
    channel: Any
    channel_addr: str
    when: datetime.datetime

    async def reply(self, reply_line: str, reply_reference: bool) -> bool:
        """Replies back at the message anyhow."""
        ...

    async def reply_channel(self, reply_line: str, reply_reference: bool) -> bool:
        """Replies back directly to the channel, if said distinction is applicable."""
        ...

    async def reply_privately(self, reply_line: str, reply_reference: bool) -> bool:
        """Replies back directly to the author."""
        ...

    def __repr__(self) -> str:
        ...


class MessageLegacy(MessageLegacyInterface, MessageProxy, typing.Protocol):
    """
    A high-level Message base class.

    This used to be implemented by backends. Nonetheless, for the sake of
    backwards compatibility, this now serves as a MessageProxy type.
    """

    def __init__(
        self,
        backend: Backend,
        line: str,
        author_name: str,
        author_addr: str,
        channel: Any,
        channel_addr: str,
        when: Optional[datetime.datetime] = None,
    ):
        self.backend = backend
        self.line = line
        self.author_name = author_name
        self.author_addr = author_addr
        self.channel = channel
        self.channel_addr = channel_addr
        self.when = when or datetime.datetime.utcnow()

    async def reply(self, reply_line: str, reply_reference: bool) -> bool:
        """Replies back at the message anyhow."""
        ...

    async def reply_channel(self, reply_line: str, reply_reference: bool) -> bool:
        """Replies back directly to the channel, if said distinction is applicable."""
        ...

    async def reply_privately(self, reply_line: str, reply_reference: bool) -> bool:
        """Replies back directly to the author."""
        ...

    def __repr__(self) -> str:
        return "{}({} in {}: {})".format(
            type(self).__name__, self.author_name, self.channel, repr(self.line)
        )

    # The MessageProxy implementation goes below.

    def origin_is_channel(self) -> bool:
        """
        Returns whether the origin of this message is a Channel.
        """
        return self.underlying.channel

    def get_channel(self) -> Optional["ChannelProxy"]:
        """
        Returns the origin channel of this message, if applicable.
        """
        return self.underlying.backend.get_channel(self.underlying.channel_addr)

    def quote_line(self) -> str:
        """
        Returns the 'quote line' of this message, in a single line of plaintext.

        This uses the IRC quote format by default (<name> message), even though
        MessageLegacy is not necessarily an IRC thing. Then again, it's legacy,
        and deprecated and most likely never implemented anyways :)
        """
        return "<{}> {}".format(self.underlying.author_name, self.underlying.line)

    def get_author(self) -> str:
        """
        Returns the author of this message, as an UserProxy's identifier string.
        """
        return self.underlying.author_addr

    def is_composite(self) -> bool:
        """
        Returns whether the message is of a composite content kind.
        """
        return False

    def get_main_line(self) -> str:
        """
        Returns the main contents of this message in a single line.
        """
        return self.underlying.line

    def get_all_lines(self) -> Iterable[str]:
        """
        If the underlying Backend supports multi-line messages, returns
        several lines of text, one string per line. Otherwise, is
        equivalent to [get_main_line()].
        """
        return [self.underlying.line]

    def get_composite(self) -> Optional[CompositeContentInstance]:
        """
        If applicable, returns the composite content instance of this message.
        """
        return None

    def get_date(self) -> datetime.datetime:
        """
        Returns the date this message was sent at.
        """
        return self.underlying.when

    def get_id(self) -> str:
        hasher = hashlib.sha256()
        hasher.update(str(id(self.underlying.backend)).encode("utf-8"))
        hasher.update(self.underlying.channel_addr.encode("utf-8"))
        hasher.update(self.underlying.author_addr.encode("utf-8"))
        hasher.update(str(self.underlying.when).encode("utf-8"))

        return hasher.digest().hex()

    def get_name(self) -> typing.Optional[str]:
        return None

    def get_backend(self) -> Backend:
        return self.underlying.backend
