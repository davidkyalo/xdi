from collections import namedtuple
from inspect import Parameter
import operator
import typing as t
from abc import ABCMeta, abstractmethod
from enum import Enum, IntEnum
from logging import getLogger
from types import FunctionType, GenericAlias, MethodType

from typing_extensions import Self
from weakref import WeakSet

import attr

from ._common import Missing, calling_frame, private_setattr
from ._common.lazy import LazyOp as BaseLazyOp

if t.TYPE_CHECKING:
    from .providers import Provider

    ProviderType = type[Provider]


T_Injected = t.TypeVar("T_Injected", covariant=True)
T_Default = t.TypeVar("T_Default")
T_Injectable = t.TypeVar("T_Injectable", bound="Injectable", covariant=True)


_logger = getLogger(__name__)

_NoneType = type(None)



_BLACKLIST = frozenset({
    None, 
    _NoneType,
    t.Any,
    type(t.Literal[1]),

    str,
    bytes,
    bytearray,
    tuple,
    
    int, 
    float,
    frozenset,
    Parameter.empty,
    Missing,

})


def is_injectable(obj):
    return isinstance(obj, Injectable) \
        and not (obj in _BLACKLIST or isinstance(obj, NonInjectable))


def is_injectable_annotation(obj):
    """Returns `True` if the given type is injectable."""
    return is_injectable(obj)


class _PrivateABCMeta(ABCMeta):
    
    def register(self, subclass):
        if not (calling_frame().get("__package__") or "").startswith(__package__):
            raise TypeError(f"virtual subclasses not allowed for {self.__name__}")

        return super().register(subclass)



class InjectableType(_PrivateABCMeta):
    
    _abc_blacklist: WeakSet

    def __new__(mcls, name, bases, namespace, /, **kwargs):
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        cls._abc_blacklist = WeakSet()
        return cls

    # def blacklist(self, cls):
    #     self._abc_blacklist.add(cls)
    #     return cls
    
    # def blacklisted(self, cls):
    #     return cls in self._abc_blacklist

    # def __instancecheck__(self, instance):
    #     """Override for isinstance(instance, cls)."""
    #     return not instance.__class__ in self._abc_blacklist \
    #         and super().__instancecheck__(instance)

    # def __subclasscheck__(self, cls):
    #     """Override for isinstance(instance, cls)."""
    #     return not cls in self._abc_blacklist \
    #         and super().__subclasscheck__(cls)



class Injectable(metaclass=InjectableType):

    __slots__ = ()

    # @classmethod
    # def __subclasshook__(cls, sub):
    #     if cls is Injectable:
    #         return not sub in cls._abc_blacklist
    #     return NotImplemented


# Injectable.blacklist(str)
# Injectable.blacklist(bytes)
# Injectable.blacklist(bytearray)
# Injectable.blacklist(tuple)
# Injectable.blacklist(int)
# Injectable.blacklist(float)
# # Injectable.blacklist(int)
# Injectable.blacklist(int)


Injectable.register(type)
Injectable.register(t.TypeVar)
Injectable.register(FunctionType)
Injectable.register(MethodType)
Injectable.register(GenericAlias)
Injectable.register(type(t.Generic[T_Injected]))
Injectable.register(type(t.Union))



class NonInjectable(metaclass=_PrivateABCMeta):
    __slots__ = ()
    def __init_subclass__(cls, *args, **kwargs):
        raise TypeError(f"Cannot subclass {cls.__name__}")


NonInjectable.register(_NoneType)
NonInjectable.register(type(t.Literal[1]))




@Injectable.register
class InjectionMarker(t.Generic[T_Injectable], metaclass=_PrivateABCMeta):

    __slots__ = ()

    @property
    @abstractmethod
    def __origin__(self): ...




@attr.s()
class InjectorLookupError(KeyError):

    abstract: Injectable = attr.ib(default=None)
    scope: 'Scope' = attr.ib(default=None)




class DepScope(IntEnum):

    any: 'DepScope'       = 0
    """Inject from any scope.
    """

    only_self: "DepScope" = 1
    """Only inject from the current scope without considering parents
    """

    skip_self: "DepScope" = 2
    """Skip the current scope and resolve from it's parent instead.
    """

_object_new = object.__new__




@InjectionMarker.register
@private_setattr
class PureDep(t.Generic[T_Injectable]):
    __slots__ = 'abstract',

    abstract: T_Injected

    scope: t.Final = DepScope.any
    default: t.Final = Missing
    has_default: t.Final = False
    injects_default: t.Final = False

    def __new__(cls: type[Self], abstract: T_Injectable) -> Self:
        if abstract.__class__ is cls:
            return abstract
        self = _object_new(cls)
        self.__setattr(abstract=abstract)
        return self

    def forward_op(op):
        def method(self: Self, *a):
            return op(self.abstract, *a)
        return method
    
    # @property
    # def __dependency__(self):
    #     return self.abstract

    __eq__ = forward_op(operator.eq)
    __ne__ = forward_op(operator.ne)
    
    __gt__ = forward_op(operator.gt)
    __ge__ = forward_op(operator.ge)

    __lt__ = forward_op(operator.lt)
    __le__ = forward_op(operator.le)

    __hash__ = forward_op(hash)
    __bool__ = forward_op(bool)

    del forward_op
    
    @property
    def provided(self):
        return Provided(self)

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}({self.abstract!s})'

    def __init_subclass__(cls, *args, **kwargs):
        raise TypeError(f"Cannot subclass {cls.__module__}.{cls.__name__}")


_AbcDepTuple = namedtuple('Dep', ('abstract', 'scope', 'default'), defaults=[DepScope.any, Missing])





_pure_dep_defaults = PureDep.scope, PureDep.default



@InjectionMarker.register
@private_setattr
class Dep(_AbcDepTuple):

    """Marks an injectable as a `dependency` to be injected."""
    
    __slots__ = ()

    abstract: T_Injectable
    scope: DepScope
    default: T_Default
    Scope = DepScope

    ANY_SCOPE: t.Final = DepScope.any
    """Inject from any scope.
    """

    ONLY_SELF: t.Final = DepScope.only_self
    """Only inject from the current scope without considering parents
    """

    SKIP_SELF: t.Final = DepScope.skip_self
    """Skip the current scope and resolve from it's parent instead.
    """
    
    def __init_subclass__(cls, *args, **kwargs):
        raise TypeError(f"Cannot subclass {cls.__module__}.{cls.__name__}")

    def __subclasscheck__(self, sub: type) -> bool:
        return sub is PureDep or self._base_subclasscheck(sub)
    
    _base_subclasscheck = _AbcDepTuple.__subclasscheck__

    def __new__(
        cls: type[Self],
        dependency: T_Injectable, 
        scope: DepScope=ANY_SCOPE,
        default=Missing,
    ):  
        if _pure_dep_defaults == (scope, default):
            return PureDep(dependency)
        else:
            return _AbcDepTuple.__new__(cls, dependency, scope, default)

    @property
    def __origin__(self):
        return self.__class__

    @property
    def has_default(self):
        return not self.default is Missing

    @property
    def injects_default(self):
        return isinstance(self.default, InjectionMarker)

    @property
    def provided(self):
        return Provided(self)



@InjectionMarker.register
class Provided(BaseLazyOp):
    
    __slots__ = () 
    __offset__ = 1

    @t.overload
    def __new__(cls: type[Self], abstract: type[T_Injected]) -> Self: ...
    __new__ = BaseLazyOp.__new__
   
    @property
    def __abstract__(self) -> type[T_Injected]:
        return self.__expr__[0]
    
    @property
    def __origin__(self):
        return self.__class__




from . import providers, injectors
from .containers import Container
from .providers import Provider
from .scopes import Scope
