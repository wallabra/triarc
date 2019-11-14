import trio
import inspect



class Backend(object):
    def __init__(self):
        self._listeners = {}

    def listen(self, name):
        def _decorator(func):
            self._listeners.setdefault(name, set()).add(func)

        return _decorator

    async def receive_message(self, kind, data):
        if kind in self._listeners:
            async with trio.open_nursery() as nursery:
                for listener in self._listeners[kind]:
                    nursery.start_soon(listener, data)