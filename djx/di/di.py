from djx.common.collections import fallbackdict, fluentdict
import logging
from functools import update_wrapper
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from collections.abc import Callable


from flex.utils.proxy import Proxy
from flex.utils.decorators import export


from .injectors import Injector, RootInjector
from .scopes import Scope, ScopeType
from .inspect import signature
from .providers import alias, provide, injectable
from . import abc
from .abc import T, T_Injected, T_Injector, T_Injectable

__all__ = [
    'injector',

]

logger = logging.getLogger(__name__)


provide(abc.Injector, alias=Injector, priority=-1)


__inj_ctxvar = ContextVar[T_Injector]('__inj_ctxvar')

__root_inj = RootInjector()

__inj_ctxvar.set(__root_inj)


injector = Proxy(__inj_ctxvar.get)

@export()
@contextmanager
def scope(name: str=None):
    cur = __inj_ctxvar.get()

    scope = Scope[name] if name else Scope[Scope.MAIN] \
        if cur is __root_inj else None

    if scope is None or scope in cur:
        reset = None
        yield cur

    elif scope not in cur:
        cur = scope().create(cur)
        reset = __inj_ctxvar.set(cur)
        try:
            with ExitStack() as stack:
                stack.push(cur)
                yield cur
        finally:
            reset is None or __inj_ctxvar.reset(reset)







head = __inj_ctxvar.get


@export()
def final():
    return __inj_ctxvar.get().final


@export()
def get(key: T_Injectable, default=None) -> T_Injected:
    return __inj_ctxvar.get().get(key, default)




@export()
def wrapped(func: Callable[..., T], /, args: tuple=(), keywords:dict={}) -> Callable[..., T]:
    params = signature(func).bind_partial(*args, **keywords)
    def wrapper(inj: Injector=None, /, *args, **kwds) -> T:
        if inj is None: 
            inj = __inj_ctxvar.get()
        # fallbackdict(params.arguments, kwds)
        return func(*params.inject_args(inj), **params.inject_kwargs(inj))
    
    update_wrapper(wrapper, func)

    return wrapper if params else func





@export()
def wrap(*args, **kwds):
    def decorate(fn):
        return wrapped(fn, args, kwds)
    return decorate




@export()
def call(func: Callable[..., T], /, args: tuple=(), keywords:dict={}) -> T:
    inj = __inj_ctxvar.get()
    params = signature(func).bind_partial(*args, **keywords)
    return func(*params.inject_args(inj), **params.inject_kwargs(inj))











