import trio
import re

from typing import Union
from triarc.backends.irc import IRCConnection, IRC_SOFT_NEWLINE



PORT = 51523

def make_mock_irc_server(cancel_scope: trio.CancelScope):
    async def mock_irc_server(client: Union[trio.SocketStream, trio.SSLStream]):
        buffer = ""

        try:
            async for data in client:
                lines = re.split(IRC_SOFT_NEWLINE, buffer + data.decode('utf-8'))
                buffer = lines.pop()

                stop = False

                for l in lines:
                    if l == '::STOP!':
                        await client.send_all(':mock.server DONE\r\n'.encode('utf-8'))
                        await client.aclose()
                        stop = True

                    else:
                        await client.send_all(':mock.server ECHO :{}\r\n'.format(l).encode('utf-8'))

                if stop:
                    await cancel_scope.cancel()
                    break

        except trio.BrokenResourceError:
            return

    return mock_irc_server

async def test_irc_server():
    scope = trio.CancelScope()

    with scope as status:
        await trio.serve_tcp(make_mock_irc_server(scope), PORT)

async def test_irc_client(nursery):
    client = IRCConnection('127.0.0.1', PORT)

    @client.listen_all()
    async def on_message(_, msg):
        print(msg.line)

    @client.listen('DONE')
    async def on_done(_, msg):
        await client.stop()

    async def do_client_things():
        await trio.sleep(0.1)
        await client._send('AAA')
        await client._send('::STOP!')

        return

    async with trio.open_nursery() as new_nursery:
        new_nursery.start_soon(client.start)
        new_nursery.start_soon(do_client_things)

async def run_test():
    async with trio.open_nursery() as nursery:
        nursery.start_soon(test_irc_server)
        nursery.start_soon(test_irc_client, nursery)

trio.run(run_test)