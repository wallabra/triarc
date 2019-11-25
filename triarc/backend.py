"""The Backend class. The base class of all Triarc backends is
here defined.
"""

import trio



class Backend:
    """Dummy backend superclass. Actual Triarc backends are supposed to subclass
    the Backend class, which provides several utilities, including those which are
    expected (and thus required) by the Triarc bot that will eventually use it."""

    def __init__(self):
        self._listeners = {}
        self._global_listeners = set()

    def listen(self, name: str = '_'):
        """Adds a listener for specific messages received in this backend.
        Use as a decorator generating method.

        Keyword Arguments:
            name {str} -- The name of the event to listen for (default: {'_'})

        Returns:
            function -- The decorator method.
        """

        def _decorator(func):
            self._listeners.setdefault(name, set()).add(func)
            return func

        return _decorator

    def listen_all(self):
        """Adds a listener for all messages received in this backend.
        Use as a decorator generating method.

        Returns:
            function -- The decorator method.
        """

        def _decorator(func):
            self._global_listeners.add(func)
            return func

        return _decorator

    async def receive_message(self, kind: str, data: any):
        """Call this function whenever a message is received in this backend.
        Used either by subclasses or to 'simulate' messages.

            >>> import trio
            >>> dummy_backend = Backend()
            >>> adjective = 'great'
            ...
            >>> @dummy_backend.listen('No')
            ... async def no(whom, data):
            ...     print("Whom?")
            ...
            >>> @dummy_backend.listen('Yes')
            ... async def yes(whom, data):
            ...     print("You should also listen to {} – {}. It's {}. :)"
            ...         .format(whom, data, adjective)
            ...     )
            ...
            >>> async def test_me():
            ...     await dummy_backend.receive_message('Yes', 'Talk')
            ...
            ...     global adjective
            ...     adjective = 'superb'
            ...
            ...     await dummy_backend.receive_message('Yes', 'Relayer')
            ...     await dummy_backend.receive_message('No',
            ...         '(I don\\'t know this band ;-;)'
            ...     )
            ...
            >>> trio.run(test_me)
            You should also listen to Yes – Talk. It's great. :)
            You should also listen to Yes – Relayer. It's superb. :)
            Whom?

        Arguments:
            kind {str} -- The kind of message (aka name argument in listen).
            data {any} -- The message's data.
        """

        async with trio.open_nursery() as nursery:
            for listener in self._listeners.get(kind, set()) | self._global_listeners:
                nursery.start_soon(listener, kind, data)

    async def start(self):
        """Starts the backend."""

        raise NotImplementedError("Please subclass backend and implement start!")

    async def stop(self):
        """Stops the backend."""

        raise NotImplementedError("Please subclass backend and implement stop!")

    async def message(self, target: str, message: str):
        """Standard backend method, which must be implemented by
        every backend. Sends a message to a target.

        Arguments:
            target {str} -- The target of the message (user, channel, etc).
            message {str} -- The message to be sent.
        """

    def message_sync(self, target: str, message: str):
        """Synchronous backend method, which must be implemented by
        every backend if possible (and raise a RuntimeError if it
        is not possible). Sends a message to a target, without blocking.

        Arguments:
            target {str} -- The target of the message (user, channel, etc).
            message {str} -- The message to be sent.
        """