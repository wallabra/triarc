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
                async def call_sync(f):
                    f(data)

                for listener in self._listeners[kind]:
                    if inspect.isasyncgenfunction(a):
                        nursery.start_soon(listener, data)

                    else:
                        nursery.start_soon(call_sync, listener)