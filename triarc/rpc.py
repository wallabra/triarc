"""Triarc's very own bidirectional JSON-RPC utilities."""

import contextlib
import json
import typing
import uuid
import warnings

import attr
import trio  # type: ignore

from . import statedhandler


class RPCResponseTarget(typing.Protocol):
    """A remote RPC target."""

    async def _object(self, obj: typing.Any):
        """Send an RPC object to this target."""
        ...

    async def close(self):
        """Ask to close this RPC target."""
        ...

    async def call(self, id: str, type: str, data: typing.Any):
        """Send a RPC call to this target."""
        await self._object({"rpc": "call", "method": type, "id": id, "data": data})

    async def status(
        self, status: str, type: str = "error", id: typing.Optional[str] = None
    ):
        """Send a RPC status to this target."""
        await self._object({"rpc": "status", "type": type, "status": status, "id": id})

    async def rpc_return(self, id: str, data: typing.Any):
        """Send a RPC return to this target."""
        await self._object({"rpc": "return", "id": id, "data": data})


@attr.s(auto_attribs=True)
class RPCCallKeeper:
    """A RPC call keeper."""

    calls: dict[
        uuid.UUID,
        tuple[
            typing.Callable[[RPCResponseTarget, typing.Any], typing.Awaitable[None]],
            typing.Callable[[RPCResponseTarget, str], typing.Awaitable[None]],
        ],
    ] = attr.Factory(dict)

    async def set_return(
        self,
        call_id: str,
        data: typing.Any,
        target: RPCResponseTarget,
    ):
        """Handle a return."""
        identifier = uuid.UUID(call_id)

        if identifier not in self.calls:
            warnings.warn(
                "Ignoring return to unknown call: {}".format(repr(identifier))
            )
            await target.status(call_id, "unknown call")

            return

        await self.calls[identifier][0](target, data)

    async def set_error(
        self,
        call_id: str,
        status: str,
        target: RPCResponseTarget,
    ):
        """Handle a call error."""
        identifier = uuid.UUID(call_id)

        if identifier not in self.calls:
            warnings.warn("Ignoring error on unknown call: {}".format(repr(identifier)))
            await target.status(call_id, "unknown call")

            return

        await self.calls[identifier][1](target, status)

    async def set_call(
        self,
        callback: typing.Optional[
            typing.Callable[[RPCResponseTarget, typing.Any], typing.Awaitable[None]]
        ] = None,
        on_error: typing.Optional[
            typing.Callable[[RPCResponseTarget, str], typing.Awaitable[None]]
        ] = None,
    ) -> uuid.UUID:
        """Sets up a call to wait for a corresponding return or an error from remote."""

        identifier = uuid.uuid4()
        data_in, data_out = trio.open_memory_channel(0)

        async def call_on_return(target: RPCResponseTarget, data):
            del self.calls[identifier]

            if callback:
                await callback(target, data)

        async def call_on_error(target: RPCResponseTarget, status):
            del self.calls[identifier]

            if on_error:
                await on_error(target, status)

        self.calls[identifier] = (call_on_return, call_on_error)
        return identifier


@attr.s(auto_attribs=True)
class RPCServer:
    """A bidirectional RPC server (and client)."""

    connection: "RPCConnection"
    call_keeper: RPCCallKeeper = attr.Factory(RPCCallKeeper)

    async def handle_call(self, name: str, data: typing.Any) -> typing.Any:
        """Handle a call."""
        self.connection.handle_call(name, data)

    async def has_method(self, name: str) -> bool:
        """Whether this RPC server has a RPC method."""
        return await self.connection.has_method(name)

    async def on_call(
        self, target: RPCResponseTarget, id: str, mtype: str, data: typing.Any
    ):
        """Handle a RPC call."""

        if await self.has_method(mtype):
            try:
                result = await self.handle_call(mtype, data)

            except Exception as err:
                await target.status(
                    "{}: {}".format(type(err).__str__, str(err)), "call error", id
                )

            else:
                await target.rpc_return(id, result)

        else:
            await target.status(mtype, "call unknown", id)

    async def on_status(
        self,
        target: RPCResponseTarget,
        type: str,
        status: str,
        id: typing.Optional[str] = None,
    ):
        """Handle a RPC status."""
        if id is not None:
            if type == "call error":
                await self.call_keeper.set_error(id, status, target)

            elif type == "call unknown":
                warnings.warn(
                    "{} tried to call an unknown method in remote '{}'".format(
                        repr(self), repr(status)
                    )
                )

    async def on_return(self, target: RPCResponseTarget, id: str, data: typing.Any):
        """Handle a RPC return."""
        await self.call_keeper.set_return(id, data, target)

    async def on_object(self, target: RPCResponseTarget, rpc_object: typing.Any):
        rpc_type = rpc_object["rpc"]

        if rpc_type == "call":
            await self.on_call(
                target,
                rpc_object["id"],
                rpc_object["type"],
                rpc_object.get("data", None),
            )

        elif rpc_type == "status":
            await self.on_status(
                target,
                rpc_object["type"],
                rpc_object["status"],
                rpc_object.get("id", None),
            )

        elif rpc_type == "return":
            await self.on_return(target, rpc_object["id"], rpc_object.get("data", None))


@attr.s(auto_attribs=True)
class RPCHandlerStateMachine(statedhandler.HandlerStateMachine):
    connection: "RPCConnection"

    states: dict[str, statedhandler.HandlingState] = attr.Factory(dict)
    state: typing.Optional[statedhandler.HandlingState] = None

    def is_on_state(self) -> bool:
        """Returns True if and only if there is a non-null current state."""
        return self.state is not None

    def get_state(self) -> typing.Optional[statedhandler.HandlingState]:
        """Get the current state object."""
        return self.state

    def set_state_name(self, state: str):
        """Set the current state by name."""
        self.state = self.states[state]

    def has_states(self, name: str) -> bool:
        """Returns True if this state exists by name."""
        return name in self.states

    def add_state(self, name: str, state: statedhandler.HandlingState):
        """Add a state by name."""
        self.states[name] = state

    async def close(self):
        """Close this handler state machine's user."""
        await self.connection.close()

    async def respond(self, data: typing.Any):
        """Respond some data back through this handler state machine."""
        await self.connection.respond(data)


class RPCStateError(BaseException):
    pass


@attr.s(auto_attribs=True)
class RPCConnection:
    """A RPC-enabled state machine with a single RPCResponseTarget."""

    target: RPCResponseTarget
    server: typing.Optional[RPCServer]
    state_machine: typing.Optional[RPCHandlerStateMachine]
    context: typing.Any = None

    @classmethod
    def create(
        cls, target: RPCResponseTarget, context: typing.Any = None
    ) -> RPCConnection:
        self = RPCConnection(target, None, None, context)

        self.server = RPCServer(self)
        self.state_machine = RPCHandlerStateMachine(self)

        return self

    async def close(self):
        """Close the associated RPC target."""
        await self.target.close()

    async def respond(self, data: typing.Any):
        """Respond some data through this RPC connection."""
        await self.target._object(data)

    async def handle_data(self, data: typing.Any):
        """Handle some data, here as RPC."""
        assert self.server is not None

        await self.server.on_object(self.target, data)

    async def handle_call(self, name: str, data: typing.Any) -> typing.Any:
        """Handle a RPC method call."""
        assert self.state_machine is not None

        state = self.state_machine.get_state()

        if state is None:
            raise RPCStateError("No state to handle RPC call!")

        callback = getattr(state, "rpc_" + name.replace('/', '_'), None)

        if not callback:
            raise RPCStateError("State has no method to handle RPC call!")

        return await callback(self, self.state_machine, self.context, data)

    async def has_method(self, name: str) -> bool:
        assert self.state_machine is not None

        """Whether this RPC server has a RPC method."""
        state = self.state_machine.get_state()

        if state is not None:
            return hasattr(state, "rpc_" + name.replace('/', '_'))

        return False


class TrioRPCTarget(RPCResponseTarget):
    """A remote RPC target over TCP."""

    connection: trio.SocketStream

    async def _object(self, obj: typing.Any):
        """Send an RPC object to this target."""
        await self.connection.send(json.dumps(obj) + "\n")

    async def close(self):
        """Ask to close this RPC target."""
        await self.connection.aclose()


@attr.s(auto_attribs=True)
class TrioRPCServer(contextlib.AbstractAsyncContextManager, typing.Protocol):
    """A RPC server using Trio that listens over TCP."""

    context: typing.Any

    bind_addr: str = "localhost"
    bind_port: int = 9580

    scope: typing.Optional[trio.CancelScope] = None
    running: bool = False

    def setup_handlers(self, machine: RPCHandlerStateMachine):
        """Setup a RPCHandlerStateMachine to handle a new Connection."""
        ...

    async def conn_handler(self, server_stream):
        target = TrioRPCTarget(server_stream)
        conn = RPCConnection(target, self.context)

        self.setup_handlers(conn.state_machine)

        # Handle lines
        line_buffer = []

        async for data in server_stream:
            fragments = data.decode("utf-8").split("\n")

            line_buffer.append(fragments[0])

            for frag in fragments[1:]:
                buffered = "".join(line_buffer)

                if buffered:
                    try:
                        data = json.loads(buffered)

                    except json.JSONError:
                        # is not JSON, close connection
                        await server_stream.send(
                            "ERROR: Is not JSON. This is a JSON RPC server. Please see:"
                            "https://github.com/Gustavo6046/triarc"
                        )

                        await server_stream.close()
                        return

                    else:
                        await conn.handle_data(data)

                if frag:
                    line_buffer = [frag]

        await server_stream.close()

    async def __aenter__(self):
        self.running = True

        with trio.CancelScope() as scope:
            self.scope = scope
            await trio.serve_tcp(self.conn_handler, self.bind_port, host=self.bind_addr)

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.running = False

        await self.scope.cancel()
