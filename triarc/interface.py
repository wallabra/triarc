#!/usr/bin/env python3
"""An interface library, to generalize member access across
multiple *existing* objects."""

import inspect

from typing import Optional, List



class InterfaceAttributeError(AttributeError):
    """
    Exception raised whenever the interface can't find a member that
    it expected to find. This isn't raised on interface instantiation,
    but rather lazily, i.e. only when such member is requested.
    """

class Interface:
    """An interface, that defines expected members, and can be
    instantiated with a list of objects (called implementors),
    returning a special object that can access members from these
    implementors (or raise NotImplementedError when an expected
    member is not there).
    """

    _init_attr = {}

    def __init__(self, implementors: List[object]):
        """
        Arguments:
            implementors {List[object]} -- A list of implementor objects
                                           to the which to bind members.
        """

        object.__setattr__(self, '_implementors', list(implementors))

        def bind_attr(name, val, source):
            if inspect.ismethod(val):
                i_self = self

                # Bind methods to their source implementors.
                class ProxySelf:
                    """A proxy class responsible for binding attributes
                    on method calls. This class is used because, internally,
                    Interface is actually calling the method on the class
                    of the implementor, instead of the implementor itself,
                    because then it can pass a ProxySelf instance and
                    bind attributes set on self.
                    """

                    def __getattribute__(self, name):
                        return getattr(i_self, name)

                    def __setattr__(self, name, val):
                        return setattr(i_self, name, val)

                proxy_self = ProxySelf()

                def _inner(*args, **kwargs):
                    unbound_func = getattr(type(source), name)
                    return unbound_func(proxy_self, *args, **kwargs)

                return _inner

            def _getter():
                return getattr(source, name)

            def _setter(val):
                return setattr(source, name, val)

            return property(_getter, _setter)

        for name, val in type(self)._init_attr.items():
            object.__setattr__(self, name, val)

        for i in self._implementors:
            for name in dir(i):
                if name.strip('_') != '' and (
                        len(name) < 4 or name[:2] != '__' or name[-2:] != '__'
                ):
                    val = getattr(i, name)
                    bound = bind_attr(name, val, i)
                    object.__setattr__(self, name, bound)

    def __getattr__(self, name):
        try:
            return super().__getattribute__(name)

        except AttributeError as err:
            for i in super().__getattribute__('_implementors'):
                if hasattr(i, name):
                    return getattr(i, name)

            raise InterfaceAttributeError(str(err))

    def __setattr__(self, name, value):
        for i in super().__getattribute__('_implementors'):
            setattr(i, name, value)

        object.__setattr__(self, name, value)

    @classmethod
    def require(cls, is_required: bool = False, required_name: Optional[str] = None) -> any:
        """This decorator class method defines an expected method, by using
        the decorated function as a default value for that method by default
        (or raising NotImplementedError otherwise).

        Keyword Arguments:
            is_required {bool} -- Whether to raise NotImplementedError if the method is not found
                                  in any implementor. (default: {False})
            required_name {Optional[str]} -- The name to expect. Defaults to the decorated
                                             function's name. (default: {None})

        Raises:
            NotImplementedError: This method was not found in any implementor, so the interface
                                 that explicitly requires it was not able to call any
                                 real implementation of it.

        Returns:
            any -- Whatever the implementation returns.
        """

        def _decorator(func):
            name = required_name or func.__name__

            def _inner(i_self: Interface, *args, **kwargs):
                if is_required:
                    raise NotImplementedError("This Interface ({}) doesn't implement {}!".format(
                        ' + '.join(
                            type(i).__name__
                            for i in object.__getattribute__(i_self, '_implementors')
                        ), name
                    ))

                func(*args, **kwargs)

            cls._init_attr[name] = _inner
            return _inner

        return _decorator
