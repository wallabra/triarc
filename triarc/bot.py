from triarc.backend import Backend



class Bot(object):
    def __init__(self, backend: Backend):
        self.backend = backend

        self.backend.listen_all()(self.on_message)

    async def on_message(self, kind, data):

    async def start(self):
        """Starts this Bot by starting its backend."""

        await self.backend.start()

    async def stop(self):
        """Stops this Bot by stopping its backend."""

        await self.backend.sto()