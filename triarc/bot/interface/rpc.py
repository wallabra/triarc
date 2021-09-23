"""A RPC server for Reactors."""

import contextlib
import json
import typing

import attr
import trio  # type: ignore

from ...rpc import RPCConnection, RPCHandlerStateMachine, TrioRPCServer
from ...statedhandler import HandlingState
from ..bot import Bot


class IdleHandler(HandlingState):
    """Handle the RPC server in the idle state."""

    id = "idle"

    async def rpc_hi(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "BotRPCServer",
        data: typing.Any,
    ) -> typing.Any:
        """Handle a greeting."""
        if data != "see, a greeting!":
            # Noise, ignore.
            return

        if context.password:
            machine.next_state("auth")
            return {"resuilt": "please authenticate"}

        else:
            machine.next_state("ready")
            return {"resuilt": "success"}

    async def rpc_auth(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "BotRPCServer",
        data: typing.Any,
    ) -> typing.Any:
        return {"result": "error", "message": "The client did not say hi beforehand."}

    async def rpc_is_ready(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "BotRPCServer",
        data: typing.Any,
    ) -> typing.Any:
        return False


class AuthHandler(HandlingState):
    """Handle the RPC server in the auth state."""

    id = "auth"

    async def rpc_auth(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "BotRPCServer",
        data: typing.Any,
    ) -> typing.Any:
        """Handle an authentication request."""
        if data != context.password:
            # Authentication failed.
            machine.next_state("idle")
            return {"resuilt": "error", "message": "Authentication failure."}

        machine.next_state("success")
        return {"resuilt": "success"}

    async def rpc_is_ready(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "BotRPCServer",
        data: typing.Any,
    ) -> typing.Any:
        return False


class ReadyHandler(HandlingState):
    """Handle the RPC server in the ready state."""

    id = "ready"

    async def rpc_register_reactor(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "BotRPCServer",
        data: typing.Any,
    ) -> typing.Any:
        """This remote RPC is a Reactor. Handle it."""

        reactor_id = data["id"]

        # WIP: add code to register reactor in bot
        # don't forget to check if id is already taken!

    async def rpc_is_ready(
        self,
        conn: RPCConnection,
        machine: RPCHandlerStateMachine,
        context: "BotRPCServer",
        data: typing.Any,
    ) -> typing.Any:
        return True


@attr.s
class BotRPCServer:
    """A RPC server that listens for connections from Reactors."""

    bot: Bot
    rpc_server: TrioRPCServer

    password: typing.Optional[str] = None

    def setup_handlers(self, machine: RPCHandlerStateMachine):
        """Setup the handlers for the RPC server."""
        machine.register_state(IdleHandler())
        machine.register_state(AuthHandler())
        machine.register_state(ReadyHandler())

        machine.next_state("idle")
