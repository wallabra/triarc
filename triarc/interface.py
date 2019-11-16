#!/usr/bin/env python3

import inspect

from typing import Set, Optional, List



class InterfaceAttributeError(AttributeError):
    pass


class Interface(object):
    _init_attr = {}

    def __init__(self, implementors: List[object]):
        object.__setattr__(self, '_implementors', list(implementors))

        def bind_attr(name, val, source):
            if inspect.ismethod(val):
                # Bind methods to their source implementors.
                class ProxySelf(object):
                    def __getattribute__(_, name): 
                        return getattr(self, name)

                    def __setattr__(_, name, val): 
                        return setattr(self, name, val)

                proxy_self = ProxySelf()

                def _inner(*args, **kwargs):
                    f = getattr(type(source), name)
                    return f(proxy_self, *args, **kwargs)

                return _inner
        
            else:
                def _getter():
                    return getattr(source, name)

                def _setter(val):
                    return setattr(source, name, val)

                return property(_getter, _setter)
                
        for name, val in type(self)._init_attr.items():
            object.__setattr__(self, name, val)

        for i in self._implementors:
            for name in dir(i):
                if name.strip('_') != '' and (len(name) < 4 or name[:2] != '__' or name[-2:] != '__'):
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

    def _implementor_names(self):
        return ' + '.join(a.__name__ for a in self._implementor)

    @classmethod
    def require(cls, is_required: bool = False, required_name: Optional[str] = None):
        def _decorator(func):
            name = required_name or func.__name__

            def _inner(self: Interface, *args, **kwargs):
                if is_required:
                    raise NotImplementedError("{} doesn't implement {}!".format(self._implementor_names(), name))

                else:
                    func(*args, **kwargs)

            cls._init_attr[name] = _inner
            return _inner

        return _decorator


if __name__ == '__main__':
    # eaxmple
    class A(object):
        def __init__(self):
            self.dog = '?'

        def woof(self):
            print("Woof!")
            self.dog = True

    class B(object):
        def __init__(self):
            self.dog = '?'
            
        def woof(self):
            print("Meow!")
            self.dog = False

    class MyInterface(Interface):
        pass
    
    @MyInterface.require(True)
    def woof(self):
        pass

    class Unrelated(object):
        def __init__(self):
            self.rich = False

        def boring(self):
            print('Stonks!')
            self.rich = True

    a = A()
    b = B()
    unrelated = Unrelated()

    print('(A)')
    MyInterface([unrelated, a]).woof()
    print('(B)')
    MyInterface([b, unrelated]).woof()
    print('(Unrelated)')
    MyInterface([unrelated, a]).boring()

    print()
    print('a is dog:', a.dog) # it was bound to MyInterface(a)
    print('b is dog:', b.dog) # it was bound to MyInterface(b)
    print('a is rich:', a.rich if hasattr(a, 'rich') else 'undefined')
    print('b is rich:', b.rich if hasattr(b, 'rich') else 'undefined')