import trio
import ssl as pyssl

from triarc.backend import Backend



class IRCConnection(Backend):
    def __init__(self, host, port=6667, ssl=None):
        """Sets up an IRC connection that can be used as
        a triarc backend.
        
        Arguments:
            host {str} -- The host of the IRC server.
        
        Keyword Arguments:
            port {int} -- The port of the IRC server. (default: 6667)
            ssl {ssl.SSLContext} -- The SSL context used (or None if not using any), (default: {None})
        """

        super().__init__()

        self.host = host
        self.port = port
        self.ssl_context = ssl

    async def start(self):
        self.connection = trio.open_tcp_stream(host, port)
        
        if ssl:
            self.connection = trio.SSLStream(self.connection, ssl)