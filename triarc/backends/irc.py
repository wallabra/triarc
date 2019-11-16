import trio
import logging
import inspect
import re
import queue
import ssl

from typing import Union, Optional
from triarc.backend import Backend
from collections import namedtuple



IRC_SOFT_NEWLINE = re.compile(r'\r?\n')

IRC_RESP_PREFIX = r':([^ \0]+) '
IRC_RESP_NUMERIC = r'([0-9]{3})'
IRC_RESP_COMMAND = r'([^ \0]+)'
IRC_RESP_PARAMS = r'((?: (?:[^\0 \n]*))*?)?(?: :([^\0\n]*))?'

IRC_RESP = '^{}(?:(?:{})|(?:{})){}$'.format(IRC_RESP_PREFIX, IRC_RESP_NUMERIC, IRC_RESP_COMMAND, IRC_RESP_PARAMS)
IRC_RESP = re.compile(IRC_RESP)



IRCResponse = namedtuple('IRCResponse', (
    'line',
    'server',
    'is_numeric',
    'kind',
    'params'
))

IRCParams = namedtuple('IRCParams', (
    'args',
    'data'
))

def irc_parse_response(resp: str) -> IRCResponse:
    """Parses an IRC server response, according to RFC 1459.

        >>> irc_parse_response(':adams.freenode.net 404 :Not Found')
        IRCResponse(server='adams.freenode.net', is_numeric=True, kind='404', params=IRCParams(args=[''], data='Not Found'))

        >>> irc_parse_response(':adams.freenode.net IS okay :a Good Word')
        IRCResponse(server='adams.freenode.net', is_numeric=False, kind='IS', params=IRCParams(args=['okay'], data='a Good Word'))
    
    Arguments:
        resp {str} -- The IRC response to parse.
    
    Returns:
        IRCResponse -- The parsed representation.
    """

    resp = IRC_RESP.match(resp)

    if not resp:
        return None

    if resp.group(2):
        is_numeric = True
        kind = resp.group(2)
    
    else:
        is_numeric = False
        kind = resp.group(3)

    args = resp.group(4).strip().split(' ')
    data = resp.group(5)

    params = IRCParams(args, data)
    return IRCResponse(resp.group(0), resp.group(1), is_numeric, kind, params)


class IRCConnection(Backend):
    def __init__(self, host: str, port: int = 6667, ssl_ctx: Optional[ssl.SSLContext] = None):
        """Sets up an IRC connection that can be used as
        a triarc backend.

            >>> conn = IRCConnection('abcd')
            >>> conn._heat
            0
            >>> print(conn.ssl_context)
            None

            >>> import ssl
            >>> conn = IRCConnection('abcd', ssl=ssl.create_default_context())
            >>> conn.ssl_context is None
            False
        
        Arguments:
            host {str} -- The host of the IRC server.
        
        Keyword Arguments:
            port {int} -- The port of the IRC server. (default: 6667)
            ssl {ssl.SSLContext} -- The SSL context used (or None if not using any), (default: {None})
        """

        super().__init__()

        self.host = host
        self.port = port
        self.ssl_context = ssl_ctx # type: Optional[ssl.SSLContext]
        self.connection = None # type: trio.SocketStream | trio.SSLStream

        self._out_queue = queue.Queue()
        self._heat = 0

        self._running = False
        self._stopping = False

        self.logger = None # type: logging.Logger
        self.stop_scopes = []

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
        with self.new_stop_scope():
            while self.running():
                self._heat = max(self._heat - 1, 0)

                await trio.sleep(1)

    def _send(self, line: str):
        self._out_queue.put((line, None))

    async def _send_and_wait(self, line: str):
        waiting = [True]

        async def post_wait():
            waiting[0] = False

        self._out_queue.put((line, post_wait))

        while waiting[0]:
            await trio.sleep(0.01)

    def new_stop_scope(self):
        scope = trio.CancelScope()
        self.stop_scopes.append(scope)

        return scope

    async def _sender(self):
        with self.new_stop_scope():
            while self.running():
                while not self._out_queue.empty():
                    self._heat += 1

                    if self._heat > 5:
                        break

                    item, on_send = self._out_queue.get()

                    await self._send(item)

                    if on_send:
                        await on_send()

                if self.running():
                    if self._heat > 5:
                        while self._heat:
                            await trio.sleep(0.2)

                    else:
                        await trio.sleep(0.1)

    async def _send(self, item: str):
        await self.connection.send_all(str(item).encode('utf-8') + b'\r\n')

    async def _receive(self, line: str):
        """
        This function is called asynchronously everytime
        the IRC backend receives a response from the
        remote host (server).

            >>> import trio
            >>> conn = IRCConnection('i.have.no.mouth.and.i.must.scream')
            >>> @conn.listen('_NUMERIC')
            ... def print_received(msg):
            ...     print(msg)
            >>> async def print_a_test():
            ...     print(await conn._receive(':skynet.ai 404 DEATH :AAAAAAAAA'))
            >>> trio.run(print_a_test)
            IRCResponse(server='skynet.ai', is_numeric=True, kind='404', params=IRCParams(args=['DEATH'], data='AAAAAAAAA'))
            True

        Arguments:
            line {str} -- A single line, after being extracted from received data, and stripped of its trailing CRLF.

        Returns:
            bool -- Whether the line is valid IRC data.
        """

        response = irc_parse_response(line)

        if not response:
            return False

        if response.is_numeric:
            received_kind = '_NUMERIC'

        else:
            received_kind = response.kind

        await self.receive_message(received_kind, response)
        return True

    async def _receiver(self):
        with self.new_stop_scope():
            while self.running():
                buffer = ''

                try:
                    async for data in self.connection:
                        lines = re.split(IRC_SOFT_NEWLINE, buffer + data.decode('utf-8'))
                        buffer = lines.pop()

                        for l in lines:
                            await self._receive(l)

                        await trio.sleep(0.01)

                except (trio.BrokenResourceError, trio.ClosedResourceError):
                    break

    async def start(self):
        """Starts the IRC connection.

            >>> import trio
            >>> PORT = 51523
            >>> async def mock_irc_server(client):
            ...     buffer = ""
            ...     try:
            ...         async for data in client:
            ...             lines = re.split(IRC_SOFT_NEWLINE, buffer + data.decode('utf-8'))
            ...             buffer = lines.pop()
            ...             for l in lines:
            ...                 if l == '::STOP!':
            ...                     raise trio.Cancelled
            ...                 else:
            ...                     await client.send_all(b':mock.server ECHO :' + l.encode('utf-8') + b'\\r\\n')
            ...     except trio.BrokenResourceError:
            ...         return
            >>> async def test_irc_server():
            ...     await trio.serve_tcp(mock_irc_server, PORT)
            >>> async def test_irc_client():
            ...     client = IRCConnection('127.0.0.1', PORT)
            ...     @client.listen('ECHO')
            ...     async def on_echo(msg):
            ...         print(msg.kind, ':' + msg.data)
            ...     async def do_client_things():
            ...         await trio.sleep(0.1)
            ...         await client._send_and_wait(b'AAA')
            ...         await client._send_and_wait(b'::STOP!')
            ...         await client.stop()
            ...     async with trio.open_nursery() as nursery:
            ...         nursery.start_soon(client.start)
            ...         nursery.start_soon(do_client_things)
            >>> async def run_test():
            ...     async with trio.open_nursery() as nursery:
            ...         nursery.start_soon(test_irc_server)
            ...         nursery.start_soon(test_irc_client)
            >>> trio.run(run_test)
            ECHO :AAA
        """

        connection = await trio.open_tcp_stream(self.host, self.port)
        
        if self.ssl_context:
            connection = trio.SSLStream(connection, self.ssl_context)

        self.connection = connection
        self._running = True

        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._cooldown)
            nursery.start_soon(self._sender)
            nursery.start_soon(self._receiver)

        self._running = False

    async def stop(self):
        self._stopping = True
        await self.connection.aclose()

        for s in self.stop_scopes:
            s.cancel()

        while self.running():
            await trio.sleep(0.01)

        self._running  = False
        self._stopping = False