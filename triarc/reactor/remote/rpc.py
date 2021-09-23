"""
The implementation of the RPC client of a Reactor.

This is the RPC client that a Reactor employs to connect to a triarc Bot.
"""

import typing

import attr
import trio

from ...rpc import RPCConnection, RPCHandlerStateMachine, TrioRPCServer
from ...statedhandler import HandlingState
from ..reactor import Reactor


class InitHandler(HandlingState):
    """Handle the RPC client in the initial state."""

    id = "init"

    async def start(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "ReactorRPCServer",
        data: typing.Any,
    ) -> typing.Any:
        """Send a greeting."""
        result = await conn.target.call("hi", "see, a greeting!")

        status = result["result"]

        if status == "please authenticate":
            await machine.next_state("auth")

        elif status == "success":
            await machine.next_state("ready")


class AuthHandler(HandlingState):
    """Handle the RPC client in the initial state."""

    id = "init"

    async def enter_rpc(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "ReactorRPCServer",
    ) -> typing.Any:
        """Handle an auth request."""
        result = await conn.target.call("auth", context.password)

        status = result["result"]

        if status == "error":
            message = result["message"]
            warnings.warn(
                "Could not authenticate via RPC: bot RPC server said '{}'".format(
                    message
                )
            )

            await machine.next_state("init")

        elif status == "success":
            await machine.next_state("ready")


class ReadyHandler(HandlingState):
    """Handle the RPC server in the ready state."""

    id = "ready"

    # WIP: ready state stuff


@attr.s
class ReactorRPCServer:
    """A RPC server that connects to a Bot's."""

    reactor: Reactor
    rpc_server: TrioRPCServer

    password: typing.Optional[str] = None

    def setup_handlers(self, machine: RPCHandlerStateMachine):
        """Setup the handlers for the RPC server."""
        machine.register_state(InitHandler())
        machine.register_state(AuthHandler())
        machine.register_state(ReadyHandler())

        machine.next_state("init")

    # WIP: finish the code for creating the TCP connection to RPC through


# WIP: implement the interface in reactor/remote/bot.py through this
# WIP: implement the interface in reactor/remote/bot.py through this
