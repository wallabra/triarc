"""
The IRC backend.

Use with great care, as IRC networks can be
rather rigid with client behavior, which includes throttling
(and is why throttling is by default enabled).
"""

import ssl
import typing
from typing import Iterable, List, Literal, Optional, Set

import attr
import trio

from ..backend import DuplexBackend
from ..bot import MessageLegacy
from ..comms.impl import (ChannelProxy, Messageable, MessageProxy, UserProxy,
                          datetime)

if typing.TYPE_CHECKING:
    from triarc.backend import Backend

    from ..comms.base import CompositeContentInstance


@attr.s(auto_attribs=True)
class IRCTarget(Messageable):
    """The IRC backend's universal Messageable implementation."""

    backend: "IRCConnection"
    target: str

    async def message_line(self, line: str) -> bool:
        """Send a single line of plaintext."""
        return await self.backend.message(self.target, line)

    async def message_lines(self, *lines: Iterable[str]) -> bool:
        """Send many lines of plaintext."""
        return all([await self.backend.message(self.target, line) for line in lines])

    async def message_composite(self, composite: "CompositeContentInstance") -> bool:
        return all(
            [
                await self.backend.message(self.target, line)
                for line in composite.get_lines()
            ]
        )


@attr.s(auto_attribs=True)
class IRCOrigin:
    full: str
    type: Literal["user" | "server"]

    # Users
    nick: str
    ident: str
    hostname: str

    @classmethod
    def create(cls: typing.Type["IRCOrigin"], origin: str) -> "IRCOrigin":
        if "!" in origin:
            nick = origin.split("!")[0]
            ident = "!".join(origin.split("@")[0].split("!")[1:])
            hostname = "@".join(origin.split("@")[1:])
            type = "user"

        else:
            type = "server"
            nick = None
            ident = None
            hostname = None

        return cls(origin, type, nick, ident, hostname)

    def is_user(self) -> bool:
        """Whether this IRCOrigin was another client."""
        return self.type == "user"

    def is_server(self) -> bool:
        """Whether this IRCOrigin was a server."""
        return self.type == "server"


class IRCError(BaseException):
    """Base class for IRC errors."""

    pass


class IRCMessageError(IRCError):
    """Error related to the handling of IRC messages."""

    pass


@attr.s(auto_attribs=True)
class IRCMessage(MessageProxy):
    """New IRCMessage, implements MessageProxy."""

    backend: "IRCConnection"
    irc_origin: IRCOrigin
    target: str
    line: str
    when: datetime.datetime

    @classmethod
    def create(
        cls: typing.Typé["IRCMessage"],
        backend: "IRCConnection",
        origin: str,
        line: str,
        target: str,
    ) -> "IRCMessage":
        """Creates an IRCMessage object for a received message."""
        return cls(
            backend, IRCOrigin.parse(origin), target, line, datetime.datetime.utcnow()
        )

    @classmethod
    def from_response(
        cls: typing.Typé["IRCMessage"],
        backend: "IRCConnection",
        response: "IRCResponse",
    ) -> "IRCMessage":
        """Creates an IRCMessage object from an IRCResponse."""

        if __debug__ and response.kind.upper() != "PRIVMSG":
            raise IRCMessageError(
                "Tried to create an IRCMessage from an IRCResponse "
                "that is not a PRIVMSG!"
            )

        return cls(
            backend,
            response.author,
            response.args[0],
            response.data,
            datetime.datetime.utcnow(),
        )

    def origin_is_channel(self) -> bool:
        """
        Returns whether the origin of this message is a Channel.
        """
        return self.target != self.backend.selfuser.user

    def get_channel(self) -> Optional["ChannelProxy"]:
        """
        Returns the origin channel of this message, if applicable.
        """
        if self.target == self.backend.selfuser.user:
            return None  # not in channel

        return self.backend.records.channels[self.target]

    def get_author(self) -> UserProxy:
        """
        Returns the author of this message.
        """
        if self.irc_origin.nick is None:
            raise IRCMessageError("Cannot handle PRIVMSGs sent from servers!")

        return self.backend.records.add_user(self.irc_origin.nick)

    def quote_line(self) -> str:
        """
        Returns the 'quote line' of this message, in a single line of plaintext.

        The result should look something like, for instance, this:

            <AntonTheIRCGuy> I said some stuff! Hooray me!
        """
        if self.origin.is_server():
            raise IRCMessageError("Cannot handle PRIVMSGs sent from servers!")

        return "<{}> {}".format(self.origin.nick, self.line)

    def get_main_line(self) -> str:
        """
        Returns the main contents of this message in a single line.
        """
        return self.line

    def get_all_lines(self) -> Iterable[str]:
        """
        If the underlying Backend supports multi-line messages, returns
        several lines of text, one string per line.
        """
        return [self.line]

    def get_composiste(self) -> Optional[CompositeContentInstance]:
        """
        If applicable, returns the composite content instance of this message.
        """
        return None

    def get_date(self) -> datetime.datetime:
        """
        Returns the date this message was sent at.
        """
        return self.when

    def is_composite(self) -> bool:
        """
        Returns whether the message is of a composite content kind.
        """
        return False


class IRCMessageLegacy(MessageLegacy):
    """Legacy implementation of IRCMessage. Kept mostly for historical reference."""

    def __init__(self, backend: "IRCConnection", line: str, origin: str, channel: str):
        super().__init__(
            backend,
            line,
            origin.split("!")[0],
            "!".join(origin.split("!")[1:]),
            channel,
            backend.host + "/" + channel,
        )

    def _split_size(self, line: str):
        while line:
            yield line[:300]
            line = line[300:]

    async def reply(self, reply_line: str, reply_reference: bool) -> bool:
        if self.channel == self.backend.nickname:
            await self.reply_privately(reply_line)

        else:
            await self.reply_channel(reply_line)

    async def reply_channel(self, reply_line: str, reply_reference: bool) -> bool:
        success = True

        if reply_reference:
            if not await self.backend.message(
                self.channel, "<{}> {}".format(self.author_name, self.line)
            ):
                success = False

        for line in self._split_size(reply_line):
            if not await self.backend.message(self.channel, line):
                success = False

        return success

    async def reply_privately(self, reply_line: str, reply_reference: bool) -> bool:
        success = True

        if reply_reference:
            if not await self.backend.message(
                self.channel, "<{}> {}".format(self.author_name, self.line)
            ):
                success = False

        for line in self._split_size(reply_line):
            if not await self.backend.message(self.channel, line):
                success = False

        return success


@attr.s(auto_attribs=True)
class IRCParams:
    args: list[str] = attr.Factory(list)
    data: Optional[str] = attr.Factory(
        lambda data: str(data) if data is not None else None
    )


@attr.s(auto_attribs=True)
class UserRecord(UserProxy):
    """An IRC user record. Also a UserProxy implementation."""

    backend: "IRCConnection"
    user: str
    orig_name: str
    online: bool = True
    is_self: bool = False
    shared_channels: set[str] = attr.Factory(set)

    @classmethod
    def create(
        cls: "UserRecord",
        backend: "IRCConnection",
        username: str,
        is_self: bool = False,
    ) -> "UserRecord":
        """Creates a new UserRecord."""
        return cls(backend, username, username, is_self=is_self)

    def get_backend(self) -> "Backend":
        """Gets the Backend that implements this object."""
        return self.backend

    def get_id(self) -> str:
        """
        Return an unique string identifier, determined by the
        backend implementation.

        Returns:
            str -- The unique identifier of this object.
        """
        return self.orig_name

    def get_name(self) -> typing.Optional[str]:
        """
        May return a human-friendly name that describes this object.
        """
        return self.user

    def as_messageable(self) -> Messageable:
        """
        Creates a target object from this user, as a Messageable-compliant
        object.
        """
        return IRCTarget(self.backend, self.user)

    def is_self(self) -> bool:
        """
        Whether this user represents the Triarc bot itself in the backend
        platform.
        """
        return self.is_self

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
        return self.online


@attr.s(auto_attribs=True)
class ChannelRecord(ChannelProxy):
    """
    A known IRC channel. Also a ChannelProxy implementation.
    """

    backend: "IRCConnection"
    channel: str
    joined: bool = True
    users: set[str] = attr.Factory(set)

    def get_backend(self) -> "Backend":
        """Gets the Backend that implements this object."""
        return self.backend

    def get_id(self) -> str:
        """
        Return an unique string identifier, determined by the
        backend implementation.

        Returns:
            str -- The unique identifier of this object.
        """
        return self.channel

    def get_name(self) -> typing.Optional[str]:
        """
        May return a human-friendly name that describes this object.
        """
        return self.channel

    def as_messageble(self) -> Messageable:
        """
        Creates a target object from this channel, as a Messageable-compliant
        object.
        """
        return IRCTarget(self.backend, self.channel)

    def list_users(self) -> typing.Optional[typing.Generator[str, None, None]]:
        """
        Generates a list of users in this channel, by backend-specific user ID.
        """
        return self.backend.list_users_at(self.channel)


@attr.s(auto_attribs=True)
class IRCResponse:
    line: str
    origin: str
    author: IRCOrigin
    is_numeric: int
    kind: str
    params: IRCParams
    # args: list[str] = attr.Factory(list)
    # data: Optional[str]

    def __repr__(self):
        return "IRCResponse({})".format(repr(self.line))

    @property
    def args(self):
        return self.params.args

    @property
    def data(self):
        return self.params.data

    @data.setter
    def data(self, value):
        self.params.data = value

    @classmethod
    def lex(resp: str) -> (str, str, str, bool, List[str], Optional[str]):
        """Splits a single IRC response line into its constituent parts."""
        if resp[0] == ":":
            resp = resp[1:]

        tokens = iter(resp.split(" "))

        origin = next(tokens)
        kind = next(tokens)

        if kind.isdigit() and len(kind) == 3:
            kind = int(kind)
            is_numeric = True

        else:
            is_numeric = False

        args = []
        data = []

        for tok in tokens:
            if data:
                data.append(" " + tok)

            elif tok[0] == ":":
                data.append(tok[1:])

            else:
                args.append(tok)

        dataline = "".join(data)
        del data

        return (resp, origin, kind, is_numeric, tuple(args), dataline)

    @classmethod
    def parse(cls: typing.Type["IRCResponse"], resp: str) -> "IRCResponse":
        """Parses an IRC server response, according to RFC 1459.

            >>> IRCResponse.parse(':zirconium.libera.chat 404 :Not Found').kind
            404

            >>> print(IRCResponse.parse(':zirconium.libera.chat IS okay :a Good Word').args[0])
            okay

        Arguments:
            resp {str} -- The IRC response to parse.

        Returns:
            IRCResponse -- The parsed representation.
        """

        resp, origin, kind, is_numeric, args, data = cls.lex(resp)
        return cls(resp, origin, IRCOrigin.create(origin), is_numeric, kind, args, data)


@attr.s
class IRCRecordStorage:
    """
    IRC state tracking.

    IRC is a stateless protocol; keeping the state
    is a client software responsibility.

    This is done in memory; future versions may include
    abstraction, and then storage backends like SQLite.
    """

    backend: "IRCConnection"
    selfuser: str

    users: dict[str, UserRecord] = attr.Factory(dict)
    channels: dict[str, ChannelRecord] = attr.Factory(dict)

    @classmethod
    def init(
        cls: typing.Type["IRCRecordStorage"], backend: "IRCConnection", selfuser: str
    ) -> tuple["IRCRecordStorage", "UserRecord"]:
        """Creates a new IRCRecordStorage."""
        self = cls(backend, selfuser)
        user = self.add_user(selfuser, True)

        return self, user

    def handle_join(self, channel: str, username: str) -> ChannelRecord:
        """Handles an IRC JOIN event."""
        user = self.add_user(username)
        chan = self.add_channel(channel)

        user.shared_channels.add(channel)
        chan.users.add(username)

        user.online = True

        if username == self.selfuser:
            chan.joined = True

        return

    def handle_nick(self, prevname: str, newname: str) -> ():
        """Handles an IRC NICK event."""
        if prevname == self.selfuser:
            self.selfuser = newname

        user = self.ddd_user(prevname)
        user.user = newname

    def handle_who(
        self, channel: str, *users: Iterable[str], on_join=True
    ) -> typing.Generator[UserRecord, None, None]:
        """Handles the user list received when a channel is joined or WHO'd."""
        chan = self.add_channel(channel)

        if on_join:
            chan.joined = True

        for username in users:
            user = self.add_user(username)

            user.channels.add(channel)
            chan.users.add(username)

            yield user

    def handle_part(self, channel: str, username: str):
        """Handles an IRC PART event."""
        user = self.add_user(username)
        chan = self.add_channel(channel)

        chan.users.remove(username)
        user.shared_channels.remove(channel)

        if username == self.selfuser:
            self.channels[channel].joined = False
            self.backend.receive_message("PART", channel)

        if not user.shared_channels:
            # assume user is already offline
            user.online = False
            self.backend.receive_message("BYE", username)

    def handle_quit(self, username: str):
        """Handles an IRC QUIT event."""
        user = self.add_user(username)

        for channel in user.channels:
            chan = self.add_channel(channel)
            chan.users.remove(username)

        self.users[user].online = False
        self.backend.receive_message("BYE", username)

    def add_user(self, username: str, is_self: bool = False) -> UserRecord:
        """Adds a new user record."""
        if username in self.users:
            return self.users[username]

        user = self.users.setdefault(
            username, UserRecord.create(self.backend, username, is_self=is_self)
        )

        self.backend.receive_message("HI", user)

        return user

    def add_channel(self, channel: str) -> ChannelRecord:
        """Adds a new channel record."""
        if channel in self.channels:
            return self.channels[channel]

        chan = self.channels.setdefault(channel, ChannelRecord(self.backend, channel))

        self.backend.receive_message("JOIN", chan)

        return chan


class IRCConnection(DuplexBackend):
    """An IRC connection. Used in order to create Triarc bots
    that function on IRC.
    """

    def __init__(
        self,
        host: str,
        port: int = 6667,
        nickname: str = "TriarcBot",
        realname: str = "The awesome Python comms bot framework",
        passw: str = None,
        nickserv_user: str = None,
        nickserv_pass: str = None,
        channels: Set[str] = (),
        pre_join_wait: float = 3.0,
        pre_login_wait: float = 5.0,
        cloaking_wait: float = 2.0,
        ssl_ctx: Optional[ssl.SSLContext] = None,
        auto_do_irc_handshake=True,
        **kwargs
    ):
        """Sets up an IRC connection that can be used as
        a triarc backend.

            >>> conn = IRCConnection('abcd')
            >>> conn._heat
            0
            >>> print(conn.ssl_context)
            None

            >>> import ssl
            >>> conn = IRCConnection('abcd', ssl_ctx=ssl.create_default_context())
            >>> conn.ssl_context is None
            False

        Arguments:
            host {str} -- The host of the IRC server.

        Keyword Arguments:
            port {int} -- The port of the IRC server. (default: 6667)

            nickname {str} -- The nickname used by this connection. {default: 'Triarc'}

            realname {str} --   The IRC 'real name' used by this connection.
                                (default: 'The awesome Python comms bot framework')

            passw {str} --  The IRC server password used by this connection, if any.
                            (default: None)

            nickserv_user {str} -- The NickServ username to identify to, if any. {default: None}
            nickserv_user {str} -- The NickServ password to identify with, if any. {default: None}

            channels {Set[str]} -- The channels to join after connecting. (default: ())

            pre_login_wait {float} -- The time to wait between sending the IRC handshake and
                                      authentication to NickServ. (default: 3.0)

            pre_join_wait {float} -- The time to wait between sending the IRC
                                     handshake and joining the first channels.
                                     Always happens after a NickServ authentication,
                                     if any, and accumulates with cloaking_wait. (default: 2.5)

            cloaking_wait {float} -- The additional delay between identifying to NickServ and
                                     autojoining listed channels. This delay is not awaited if
                                     there is no NickServ authentication. (default: 2.0)

            ssl_ctx {ssl.SSLContext} -- The SSL context used (or None if not using any).
                                        (default: None)

            auto_do_irc_handshake {bool} -- Whether to do the IRC handshake (i.e. initial
                                            commands, like USER, NICK, etc.) automatically
                                            when running the start method. (default: true)
        """

        super().__init__(**kwargs)

        self.host = host
        self.port = port
        self.ssl_context = ssl_ctx  # type: Optional[ssl.SSLContext]
        self.connection = None  # type: trio.SocketStream | trio.SSLStream

        self.records, self.selfuser = IRCRecordStorage.init(self, nickname)

        self.receive_message("HI", self.selfuser)

        self.nickname = nickname
        self.realname = realname
        self.passw = passw
        self.join_channels = set(channels)
        self.pre_join_wait = pre_join_wait
        self.pre_login_wait = pre_login_wait
        self.cloaking_wait = cloaking_wait

        self._running = False
        self._stopping = False

        self.auto_do_irc_handshake = auto_do_irc_handshake

        if nickserv_pass:
            self.nickserv = (nickserv_user, nickserv_pass)

        else:
            self.nickserv = None

    def running(self):
        """Returns whether this IRC connection is still up and running.

            >>> conn = IRCConnection('this.does.not.exist')
            >>> conn.running()
            False

        Returns:
            bool -- Self-explanatory.
        """

        return self._running and not self._stopping

    async def _cooldown(self):
        """
        This async loop is responsible for 'cooling' the bot
        down, at a specified frequency. It's part of the
        throttling mechanism.
        """

        if self.throttle:
            with self.new_stop_scope():
                while self.running():
                    self._heat = max(self._heat - 1, 0)

                    await trio.sleep(1 / self.cooldown_hertz)

    async def send(self, line: str):
        """
        Queues to send a raw IRC command (string).
        May be throttled. This function
        blocks, because it must emit the _SENT event.

        Arguments:
            line {str} -- The line to send.
        """

        waiting = [True]

        async def post_wait():
            waiting[0] = False

        self._out_queue.put((line, post_wait))

        with self.new_stop_scope():
            while waiting[0]:
                await trio.sleep(0.05)

    async def _sender(self):
        """
        This async loop is responsible for sending messages,
        handling throttling, and other similar things.
        """

        with self.new_stop_scope():
            while self.running():
                while not self._out_queue.empty():
                    if self.throttle:
                        self._heat += 1

                        if self._heat > self._max_heat:
                            break

                    item, on_send = self._out_queue.get()

                    await self._send(item)

                    if on_send:
                        await on_send()

                    await self.receive_message("_SENT", item)

                if self.running():
                    if self._heat > self._max_heat and self.throttle:
                        while self._heat:
                            await trio.sleep(0.2)

                    else:
                        await trio.sleep(0.05)

    async def _send(self, item: str):
        await self.connection.send_all(str(item).encode("utf-8") + b"\r\n")

    async def _receive(self, line: str):
        """
        This function is called asynchronously everytime
        the IRC backend receives a response from the
        remote host (server).

            >>> import trio
            >>> conn = IRCConnection('i.have.no.mouth.and.i.must.scream')
            ...
            >>> @conn.listen('IRC__NUMERIC')
            ... async def print_received(_, msg):
            ...     print(msg)
            ...
            >>> async def print_a_test():
            ...     print(await conn._receive(':skynet.ai 404 DEATH :AAAAAAAAA'))
            ...
            >>> trio.run(print_a_test)
            ...
            IRCResponse('skynet.ai 404 DEATH :AAAAAAAAA')
            True

        Arguments:
            line {str} --   A single line, after being extracted from received data, and
                            stripped of its trailing CRLF.

        Returns:
            bool -- Whether the line is valid IRC data.
        """

        await self.receive_message("_RAW", line)

        if line.split(" ")[0].upper() == "PING":
            data = " ".join(line.split(" ")[1:])
            await self.send("PONG " + data)

            return True

        response = IRCResponse.parse(line)

        if not response:
            return False

        if response.is_numeric:
            received_kind = "_NUMERIC"

        else:
            received_kind = response.kind

        await self.receive_message("IRC_" + received_kind, response)

        if not response.is_numeric:
            if response.kind.upper() == "PRIVMSG":
                await self.receive_message(
                    "MESSAGE", IRCMessage.from_response(self, response)
                )

            elif "!" in response.origin:
                # is user
                nick = response.origin.split("!")[0]

                if response.kind.upper() == "JOIN":
                    self.records.handle_join(response.args[0], nick)

                elif response.kind.upper() == "PART":
                    self.records.handle_part(response.args[0], nick)

                elif response.kind.upper() == "QUIT":
                    self.records.handle_quit(nick)

                elif response.kind.upper() == "NICK":
                    self.records.handle_nick(nick, response.args[0])

        elif response.numeric == 353:
            # RPL_NAMREPLY
            self.records.handle_who(
                response.args[0],
                [
                    (uname[1:] if uname[0] in "@%+" else uname)
                    for uname in response.data.split(" ")
                ],
                on_join=False,
            )

        if received_kind.upper() == "PING":
            await self.send(
                "PONG {} :{}".format(" ".join(response.args), response.data)
            )

            return True

        return True

    async def _receiver(self):
        with self.new_stop_scope():
            while self.running():
                buf = ""

                try:
                    async for data in self.connection:
                        data = buf + data.decode("utf-8")

                        while "\n" in data:
                            line, data = data.split("\n", 1)

                            if line[-1] in "\r":
                                line = line[:-1]

                            await self._receive(line)

                        buf = data
                        await trio.sleep(0.05)

                except (trio.BrokenResourceError, trio.ClosedResourceError):
                    break

    async def send_irc_handshake(self):
        """
        Sends the IRC handshake, including
        nickname, real name, and optionally
        the server password.
        """

        with self.new_stop_scope():
            await self.send("NICK " + self.nickname.split(" ")[0])
            await self.send(
                "USER {} * * :{}".format(self.nickname.split(" ")[0], self.realname)
            )

            if self.passw:
                await self.send("PASS {}".format(self.passw))

            if self.nickserv:
                await trio.sleep(self.pre_login_wait)

                n_user, n_pass = self.nickserv
                await self.message(
                    "NickServ",
                    "IDENTIFY {}{}".format(" " + n_user if n_user else "", n_pass),
                )

                await trio.sleep(self.cloaking_wait)

            await trio.sleep(self.pre_join_wait)

            for chan in self.join_channels:
                await self.join(chan)

            # Prevent joining the same channels again (e.g. if the bot is
            # kicked/banned from them and send_irc_handshake is called again).
            self.join_channels = set()

    async def start(self):
        """
        Starts the IRC connection.
        """

        connection = await trio.open_tcp_stream(self.host, self.port)

        if self.ssl_context:
            connection = trio.SSLStream(connection, self.ssl_context)

        self.connection = connection
        self._running = True

        async with trio.open_nursery() as nursery:

            async def _loaded_stop_scopes():
                nursery.start_soon(self._cooldown)
                nursery.start_soon(self._sender)
                nursery.start_soon(self._receiver)

                if self.auto_do_irc_handshake:
                    nursery.start_soon(self.send_irc_handshake)

            nursery.start_soon(self._watch_stop_scopes, _loaded_stop_scopes)

        self._running = False

    async def stop(self):
        self._stopping = True

        for scope in self.stop_scopes:
            scope.cancel()

        await self.connection.aclose()

        while self.running():
            await trio.sleep(0.05)

        self._running = False
        self._stopping = False

    # === IRC commands ===

    async def join(self, channel: str, chan_pass: Optional[str] = None):
        """Joins an IRC channel

        Arguments:
            channel {str} -- The name of the channel.

        Keyword Arguments:
            chan_pass {Optional[str]} -- An optional channel password. (default: {None})
        """

        if chan_pass:
            await self.send("JOIN {} :{}".format(channel, chan_pass))

        else:
            await self.send("JOIN {}".format(channel))

    async def leave(self, channel: str, reason: Optional[str] = None):
        """Leaves an IRC channel.

        Arguments:
            channel {str} -- The channel to leave.

        Keyword Arguments:
            reason {Optional[str]} --   The reason for which the channel has been left, if any.
                                        (default: {None})
        """

        if reason:
            await self.send("PART {} :{}".format(channel, reason))

        else:
            await self.send("PART {}".format(channel))

    async def message(self, target: str, message: str):
        """Sends a message to an IRC target (nickname or channel).

        Arguments:
            target {str} -- The IRC target. Can either be another client or a channel.
            message {str} -- The message.
        """

        await self.send(
            "PRIVMSG {} :{}".format(target, self._mutate_reply(target, message))
        )

    def message_sync(self, target: str, message: str):
        self._out_queue.put(("PRIVMSG {} :{}".format(target, message), None))

    def get_channel(self, addr: str) -> Optional[ChannelProxy]:
        """Returns a ChannelProxy from a channel address or identifier."""
        return self.records.add_channel(addr)

    def get_user(self, addr: str) -> Optional[UserProxy]:
        """Returns an UserProxy from an user address or identifier."""
        return self.records.add_user(addr)
