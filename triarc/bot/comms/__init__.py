"""
# Basic communications definitions.

All digital communication platforms that Triarc support share
three common base concepts.

### The user

An actor entity capable of sending and receiving messages.

Triarc is not a simulation, but rather a window into a communication
space; in a way, a Bot manages a set of connections, where each
connection is its own user in the communication platform it is connected
to. For this reason, Triarc handles sending messages to users, as well as
receiving from them, whether directly or otherwise.

## The message

A perhaps composite, yet atomic, unit of communication.

A message contains some communication content which usually
may be represented in plaintext. It always has one single author user
associated.

## The channel

A communication distribution node.

A place where any number of users can be associated to, everyone simultaneously
able to publish messages in it and subscribe to messages sent by all others
associated to said place.
"""
