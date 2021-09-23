"""Asynchronous data/command handler abstract library."""

import json
import typing
import warnings

import attr
import trio  # type: ignore


@attr.s
class HandlingState:
    """Class for a state of handling."""

    id: str

    async def enter(self, machine: HandlerStateMachine):
        """Called when entering this state."""
        pass

    async def exit(self, machine: HandlerStateMachine):
        """Called when exiting this state."""
        pass

    async def handle(
        self, machine: HandlerStateMachine, data: typing.Any
    ) -> typing.Optional[str]:
        """Handle a command, and optionally return the next state's ID."""
        pass


@attr.s(auto_attribs=True)
class HandlerStateMachine(typing.Protocol):
    """Class for a state machine that can handle asynchronously, with states."""

    def is_on_state(self) -> bool:
        """Returns True if and only if there is a non-null current state."""
        ...

    def get_state(self) -> typing.Optional[HandlingState]:
        """Get the current state object."""
        ...

    def set_state_name(self, state: str):
        """Set the current state by name."""
        ...

    def has_state(self, name: str) -> bool:
        """Returns True if this state exists by name."""
        ...

    def add_state(self, name: str, state: HandlingState):
        """Add a state by name."""
        ...

    def register_state(self, handler: HandlingState) -> bool:
        """Register a handling state.

        Returns True if and only if handler.name was already a registered
        Handler.
        """
        if self.has_state(handler.id):
            return True

        self.add_state(handler.id, handler)
        return False

    async def next_state(self, state: str) -> bool:
        """Try to switch to the next state.

        Returns True if and only if the state exists and was switched to."""

        if not self.has_state(state):
            return False

        if self.is_on_state():
            await self.get_state().exit(self)

        self.set_state_name(state)

        if self.is_on_state():
            await self.get_state().enter(self)

        return True

    async def close(self):
        """Close this handler state machine's user."""
        ...

    async def respond(self, data: typing.Any):
        """Respond some data back through this handler state machine."""
        ...

    async def handle_data(self, data: typing.Any):
        state = self.get_state()

        if state is not None:
            next_state = await state.handle(self, data)

            if next_state is not None:
                self.next_state(next_state)
