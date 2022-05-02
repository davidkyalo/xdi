from functools import wraps
from inspect import Parameter, signature
from itertools import chain
from logging import getLogger
import operator
from types import GenericAlias, new_class
import typing as t
from abc import ABC, ABCMeta, abstractmethod
from collections import abc, namedtuple
from enum import Enum, IntEnum, IntFlag, auto

from typing_extensions import Self
from weakref import WeakKeyDictionary, ref


from .core import Injectable, T_Default, T_Injectable, T_Injected
from ._common import Missing, private_setattr
from ._common.lookups import Lookup as BaseLookup


if t.TYPE_CHECKING: # pragma: no cover
    from .containers import Container
    from .scopes import Scope


logger = getLogger(__name__)

__static_makers = {
    t.Union,
    t.Annotated,
}


@t.overload
def is_dependency_marker(obj: 'DependencyMarker') -> True: ...
@t.overload
def is_dependency_marker(obj: object) -> False: ...
def is_dependency_marker(obj:t.Any, ind=0) -> bool:
    """Check if object is a `DependencyMarker`
    Args:
        obj (Any): the object to check

    Returns:
        bool: 
    """
    return isinstance(obj, (DependencyMarker, DependencyMarkerType)) \
            or obj in __static_makers \
            or (not not (orig := t.get_origin(obj)) and is_dependency_marker(orig))



class DependencyMarkerType(ABCMeta):
    ...


class DependencyMarker(Injectable, t.Generic[T_Injectable], metaclass=DependencyMarkerType):
    """Abstract base class for dependency markers. 

    Dependency markers are used reperesent and/or annotate dependencies. 
    """
    __slots__ = ()

    @property
    @abstractmethod
    def __origin__(self): ...


class InjectionDescriptor(Injectable, t.Generic[T_Injectable]):

    __slots__ = ()

    @property
    @abstractmethod
    def __abstract__(self) -> T_Injectable: ...



_object_new = object.__new__


_3_nones = None, None, None

_T_Start = t.TypeVar('_T_Start', int, 'ProPredicate', None)
_T_Stop = t.TypeVar('_T_Stop', int, 'ProPredicate', None)
_T_Step = t.TypeVar('_T_Step', int, None)

_T_PredVar = t.TypeVar('_T_PredVar', covariant=True)
_T_PredVars = t.TypeVar('_T_PredVars', bound=tuple, covariant=True)
_T_Pred = t.TypeVar('_T_Pred', bound='ProPredicate', covariant=True)



@private_setattr
class _PredicateOpsMixin(t.Generic[_T_PredVars]):
    
    __slots__ = ()

    def __or__(self, x):    
        if isinstance(x, ProPredicate):
            if x ==  self:
                return self
            return ProOrPredicate(self, x)
        return NotImplemented

    def __and__(self, x):
        if isinstance(x, ProPredicate):
            if x ==  self:
                return self
            return ProAndPredicate(self, x)
        return NotImplemented
   
    def __invert__(self, x):
        if isinstance(x, ProPredicate):
            return ProInvertPredicate(self)
        return NotImplemented



class _PredicateCompareMixin:
    
    __slots__ = ()

    def __eq__(self, o) -> bool:
        if isinstance(o, self.__class__):
            return self.vars == o.vars
        return NotImplemented

    def __ne__(self, o) -> bool:
        if isinstance(o, self.__class__):
            return self.vars != o.vars
        return NotImplemented

    def __forward_op(op):

        @wraps(op)
        def method(self: Self, *a):
            ident = self.vars
            if not a:
                return op(ident)
            elif isinstance(a := a[0], ProPredicate):
                return op(ident, a.vars)
            return NotImplemented

        return method

    __ge__, __gt__ = __forward_op(operator.ge), __forward_op(operator.gt)
    __le__, __lt__ = __forward_op(operator.le), __forward_op(operator.lt)

    __hash__ = __forward_op(hash)
    
    del __forward_op




class ProPredicate(_PredicateOpsMixin[_T_PredVars], _PredicateCompareMixin, ABC):
    
    __slots__ = 'vars',

    vars: _T_PredVars

    def __new__(cls, *vars: _T_PredVar):
        self = _object_new(cls)
        self.__setattr(vars=vars)
        return self

    @abstractmethod
    def pro_entries(self, it: abc.Iterable['Container'], scope: 'Scope', src: 'DepSrc') -> abc.Iterable['Container']:
        raise NotImplementedError(f'{self.__class__.__qualname__}.pro_entries()')

    @classmethod
    def __subclasshook__(cls, sub):
        if cls is ProPredicate:
            return callable(getattr(sub, 'pro_entries', None))
        return NotImplemented






@ProPredicate[tuple[_T_PredVar]].register
class ProEnumPredicate(_PredicateOpsMixin[tuple[_T_PredVar]], _PredicateCompareMixin):

    __slots__ = 'vars',

    vars: tuple[_T_PredVar]

    def __new__(cls, vars: _T_PredVar):
        self = _object_new(cls)
        self.__setattr(vars=(vars,))
        return self

    __setattr__ = object.__setattr__


class _AccessLevel(ProEnumPredicate[int]):
    __slots__ = ()



class AccessLevel(_AccessLevel, Enum):  
    """Access level for dependencies

    Attributes:
        public (AccessLevel): public
        protected (AccessLevel): protected
        guarded (AccessLevel): guarded
        private (AccessLevel): private
    """

    public: "AccessLevel" = 1
    protected: "AccessLevel" = 2
    guarded: "AccessLevel" = 3
    private: "AccessLevel" = 4
    
    __empties = frozenset((None, 0, (0,), (None,)))

    @classmethod
    def _missing_(cls, val):
        if val in cls.__empties:
            return cls.public
        return super()._missing_(val)

    def pro_entries(self, it: abc.Iterable['Container'], scope: 'Scope', src: 'DepSrc') -> abc.Iterable['Container']:
        return tuple(c for c in it if self in c.access_level(src.container))

    def __contains__(self, obj) -> bool:
        if isinstance(obj, AccessLevel):
            return self.vars >= obj.vars
        elif obj in self.__empties:
            return False
        return NotImplemented


class _ScopePredicate(ProEnumPredicate[int]):
    __slots__ = ()




class ScopePredicate(_ScopePredicate, Enum):
    """The context in which to provider resolution.
    """

    only_self: "ScopePredicate" = True
    """Only inject from the current scope without considering parents"""

    skip_self: "ScopePredicate" = False
    """Skip the current scope and resolve from it's parent instead."""
    
    def pro_entries(self, it: abc.Iterable['Container'], scope: 'Scope', src: 'DepSrc') -> abc.Iterable['Container']:
        if (scope is src.scope,) == self.vars:
            return it
        return ()



PUBLIC: AccessLevel = AccessLevel.public
"""public access level"""

PROTECTED: AccessLevel = AccessLevel.protected
"""protected access level"""

GUARDED: AccessLevel = AccessLevel.guarded
"""guarded access level"""

PRIVATE: AccessLevel = AccessLevel.private
"""private access level"""

ONLY_SELF: ScopePredicate = ScopePredicate.only_self
"""Only inject from the current scope without considering parents"""

SKIP_SELF: ScopePredicate = ScopePredicate.skip_self
"""Skip the current scope and resolve from it's parent instead."""





@private_setattr
class ProNoopPredicate(ProPredicate):

    __slots__ = ()

    vars = ()
    __pred = None

    def __new__(cls):
        if self := cls.__pred:
            return self
        self = cls.__pred = _object_new(cls)
        return self

    def pro_entries(self, it: abc.Iterable['Container'], *args) -> abc.Iterable['Container']:
        return it



@private_setattr
class ProOperatorPredicate(ProPredicate[tuple[_T_Pred]]):

    __slots__ = ()

    @staticmethod
    @abstractmethod
    def operate(*pros: abc.Set['Container']) -> abc.Iterable['Container']:
        ...

    def pro_entries(self, it: abc.Iterable['Container'], *args) -> abc.Iterable['Container']:
        it = tuple(it)
        res = self.operate(*({*pred.pro_entries(it, *args)} for pred in self.vars))
        return sorted(res, key=it.index)




class ProOrPredicate(ProOperatorPredicate[tuple[_T_Pred]]):

    __slots__ = ()

    operate = staticmethod(operator.or_)
   
   

class ProAndPredicate(ProOperatorPredicate[tuple[_T_Pred]]):
    
    __slots__ = ()

    operate = staticmethod(operator.and_)
   

class ProSubPredicate(ProOperatorPredicate[tuple[_T_Pred]]):

    __slots__ = ()

    operate = staticmethod(operator.sub)



class ProInvertPredicate(ProSubPredicate[tuple[_T_Pred]]):

    __slots__ = ()

    def __new__(cls: type[Self], right: _T_Pred) -> Self:
        return super().__new__(cls, _noop_pred, right)








class ProSlice(ProPredicate[tuple[_T_Start, _T_Stop, _T_Step]]):
    """Represents a slice or the _Provider resolution order_"""

    __slots__ = ()

    # vars: tuple[_T_ProStart, _T_ProStop, _T_ProStep]

    def __new__(cls: type[Self], start: _T_Start=None, stop: _T_Stop=None, step: _T_Step=None) -> Self:
        if not start is None is stop is step:
            if start.__class__ is cls:
                return start
            elif isinstance(start, tuple):
                start, stop, step = start + _3_nones[:len(start) - 3]
      
        return super().__new__(start, stop, step)

    @property
    def start(self):
        return self.vars[0]

    @property
    def stop(self):
        return self.vars[1]

    @property
    def step(self):
        return self.vars[2]

    def pro_entries(self, it: abc.Iterable['Container'], scope: 'Scope', src: 'DepSrc') -> abc.Iterable['Container']:
        from .containers import Container
        it = tuple(it)
        start, stop, step = self.vars
        if isinstance(start, Container):
            start = it.index(start)
        
        if isinstance(stop, Container):
            stop = it.index(stop)
        return it[start:stop:step]        

    def __iter__(self):
        yield from self.vars
        
    def __repr__(self) -> str:
        start, stop, step = self
        return f'[{start}:{stop}:{step}]'




_T_FilterPred = t.TypeVar('_T_FilterPred', bound=abc.Callable[..., bool], covariant=True)
class ProFilter(ProPredicate[tuple[_T_FilterPred, int]]):
    
    __slots__ = ()

    def __new__(cls: type[Self], filter: _T_FilterPred, extra_args: int=None) -> Self:
        if extra_args is None:
            try:
                sig = signature(filter)    
            except Exception:
                extra_args = 0
            else:
                extra_args = len(sig.parameters) - 1
                if extra_args > 1 or any(p.kind is Parameter.VAR_POSITIONAL for p in sig.parameters.values()):
                    extra_args = max(2, extra_args)
        return super().__new__(cls, filter, extra_args)

    def pro_entries(self, it: abc.Iterable['Container'], *args) -> abc.Iterable['Container']:
        fn, ln = self.vars
        args = args[:ln]
        return tuple(c for c in it if fn(c, *args))



_noop_pred = ProNoopPredicate()


class DepSrc(t.NamedTuple):
    container: 'Container'
    scope: 'Scope' = None
    predicate: ProPredicate = _noop_pred




@private_setattr
class DepKey:

    __slots__ = 'abstract', 'src', '_ash',

    abstract: Injectable
    src: DepSrc

    scope: 'Scope' = None

    def __init_subclass__(cls, scope=None) -> None:
        cls.scope = scope
        return super().__init_subclass__()

    def __new__(cls: type[Self], abstract: Injectable, container: 'Container'=None, predicate: ProPredicate=ProNoopPredicate()) -> Self:
        self, src = _object_new(cls), DepSrc(
            container, 
            cls.scope,
            predicate or _noop_pred
        )
        self.__setattr(abstract=abstract, src=src, _ash=hash((abstract, src)))
        return self

    @property
    def container(self):
        return self.src.container

    @property
    def predicate(self):
        return self.src.predicate

    def replace(self, *, abstract: Injectable=None, container: 'Container'=None, predicate: ProPredicate=None):
        return self.__class__(
            abstract or self.abstract,
            container or self.container,
            predicate or self.predicate,
        )

    def __and__(self, x):
        if isinstance(x, ProPredicate):
            return self.replace(predicate=self.predicate & x)
        return NotImplemented
    
    def __rand__(self, x):
        if isinstance(x, ProPredicate):
            return self.replace(predicate=x & self.predicate)
        return NotImplemented
    
    def __or__(self, x):
        if isinstance(x, ProPredicate):
            return self.replace(predicate=self.predicate | x)
        return NotImplemented

    def __ror__(self, x):
        if isinstance(x, ProPredicate):
            return self.replace(predicate=x | self.predicate)
        return NotImplemented

    def __eq__(self, o) -> bool:
        if isinstance(o, DepKey):
            return o.abstract == self.abstract and o.src == self.src
        return NotImplemented
        
    def __ne__(self, o) -> bool:
        if isinstance(o, DepKey):
            return o.abstract != self.abstract or o.src != self.src
        return NotImplemented
    
    def __hash__(self) -> int:
        return self._ash
       
       




@private_setattr
class PureDep(DependencyMarker, t.Generic[T_Injectable]):
    """Explicitly marks given injectable as a dependency. 

    Attributes:
        abstract (T_Injectable): the marked dependency.

    Params:
        abstract (T_Injectable): the dependency to mark.
    """
    
    __slots__ = "_ident",

    _ident: T_Injected

    default: T_Default = Missing
    predicate: ProPredicate = ProNoopPredicate()

    # scope: ScopePredicate = ScopePredicate.any
    has_default: bool = False
    injects_default: bool = False
    # container: t.Union[_ProContext, 'ProSlice', 'Container'] = _ProContext.this

    def __new__(cls: type[Self], abstract: T_Injectable) -> Self:
        if abstract.__class__ is cls:
            return abstract
        self = _object_new(cls)
        self.__setattr(_ident=abstract)
        return self

    @property
    def abstract(self) -> T_Injectable:
        return self._ident

    @property
    def lookup(self):
        return Lookup(self)

    @property
    def __origin__(self): return self.__class__

    def __copy__(self):
        return self

    def __reduce__(self):
        return self.__class__, (self._ident,)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.abstract!s})"

    def __init_subclass__(cls, *args, **kwargs):
        if not cls.__module__.startswith(__package__):
            raise TypeError(f"Cannot subclass {cls.__module__}.{cls.__qualname__}")
    
    def _as_dict(self):
        return {
            'abstract': self.abstract,
            'predicate': self.predicate,
            'default': self.default,
        }

    def replace(self, **kwds):
        return Dep(*(self._as_dict() | kwds).values())

    def __eq__(self, x) -> bool:
        cls = self.__class__
        if cls is PureDep:
            return self._ident == x
        elif isinstance(x, cls):
            return self._ident == x._ident
        return NotImplemented

    def __ne__(self, x) -> bool:
        cls = self.__class__
        if cls is PureDep:
            return self._ident != x
        elif isinstance(x, cls):
            return self._ident != x._ident
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._ident)

    def __and__(self, x):
        if isinstance(x, ProPredicate):
            return self.replace(predicate=self.predicate & x)
        return NotImplemented
    
    def __rand__(self, x):
        if isinstance(x, ProPredicate):
            return self.replace(predicate=x & self.predicate)
        return NotImplemented
    
    def __or__(self, x):
        if isinstance(x, ProPredicate):
            return self.replace(predicate=self.predicate | x)
        return NotImplemented

    def __ror__(self, x):
        if isinstance(x, ProPredicate):
            return self.replace(predicate=x | self.predicate)
        return NotImplemented




_pure_dep_default_set = frozenset([
    (PureDep.predicate, PureDep.default),
])

@private_setattr
class Dep(PureDep):

    """Marks an injectable as a `dependency` to be injected."""

    __slots__ = '_ash'

    def __new__(
        cls: type[Self],
        abstract: T_Injectable,
        predicate: ProPredicate = ProNoopPredicate(),
        default = Missing,
    ):
        
        ident = abstract, predicate or _noop_pred, default
        if ident[1:] in _pure_dep_default_set:
            if abstract.__class__ in (cls, PureDep):
                return abstract
            return PureDep(abstract)

        self = _object_new(cls)
        self.__setattr(_ident=ident)
        return self

    @property
    def __origin__(self):
        return self.__class__

    @property
    def abstract(self):
        return self._ident[0]

    @property
    def predicate(self):
        return self._ident[1]

    @property
    def default(self):
        return self._ident[2]

    @property
    def has_default(self):
        return not self.default is Missing

    @property
    def injects_default(self):
        return isinstance(self.default, DependencyMarker)

    def __hash__(self):
        try:
            return self._ash
        except AttributeError:
            self.__setattr(_ash=hash(self._ident))
            return self._ash

    def __repr__(self) -> str:
        abstract, predicate, default = self.abstract, self.predicate, self.default
        return f'{self.__class__.__qualname__}({abstract=}, {predicate=!r}, {default=!r})'



@InjectionDescriptor.register
class Lookup(DependencyMarker, BaseLookup):
    """Represents a lazy lookup of a given dependency.

    Attributes:
        __abstract__ (Injectable): the dependency to lookup.

    Params:
        abstract (Injectable): the dependency to lookup.
    """

    __slots__ = ()
    __offset__ = 1

    @t.overload
    def __new__(cls: type[Self], abstract: type[T_Injected]) -> Self:
        ...

    __new__ = BaseLookup.__new__

    @property
    def __abstract__(self) -> type[T_Injected]:
        return self.__expr__[0]

    @property
    def __origin__(self):
        return self.__class__


