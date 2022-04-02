from dataclasses import Field, field, make_dataclass, fields as dataclass_fields, is_dataclass
from collections.abc import MutableMapping, Mapping, Iterable, Collection, Set, Iterator
from enum import (
    EnumMeta as BaseEnumMeta,
    Enum as BaseEnum, 
    IntEnum as BaseIntEnum,
    IntFlag as BaseIntFlag,
    Flag as BaseFlag,
    auto as _auto,
    unique,
    auto,
)
from functools import cache, reduce
from itertools import chain
import re
from types import MappingProxyType
import warnings
import typing as t

from .functools import export
from .collections import frozenorderedset

__all__ = []

if t.TYPE_CHECKING:
    def auto():
        return _auto()



try:
    from enum import _decompose, _high_bit
except ImportError:


    def _high_bit(value):
        """
        returns index of highest bit, or -1 if value is zero or negative
        """
        return value.bit_length() - 1

        
    def _decompose(flag, value):
        """
        Extract all members from the value.
        """
        # _decompose is only called if the value is not named
        not_covered = value
        negative = value < 0
        members = []
        for member in flag:
            member_value = member.value
            if member_value and member_value & value == member_value:
                members.append(member)
                not_covered &= ~member_value
        if not negative:
            tmp = not_covered
            while tmp:
                flag_value = 2 ** _high_bit(tmp)
                if flag_value in flag._value2member_map_:
                    members.append(flag._value2member_map_[flag_value])
                    not_covered &= ~flag_value
                tmp &= ~flag_value
        if not members and value in flag._value2member_map_:
            members.append(flag._value2member_map_[value])
        members.sort(key=lambda m: m._value_, reverse=True)
        if len(members) > 1 and members[0].value == value:
            # we have the breakdown, don't need the value member itself
            members.pop(0)
        return members, not_covered



def _get_member_names(attrs, factory=list, default=None):
    f = factory and callable(factory) \
        and (lambda: factory((a for a in attrs if a[0] == '_' == a[-1])))
    return getattr(attrs, '_member_names', f and f() or default)


def _humanize(value):
	if not value:
		return str(value)
	text = re.sub('(.)([A-Z][a-z]+)', r'\1 \2', str(value))
	text = re.sub('([a-z0-9.])([A-Z])', r'\1 \2', text)
	text = re.sub('(\.)([^\s.])', r'\1 \2', text)
	return re.sub(r'_+', ' ', text)


_MT = t.TypeVar('_MT', 'Enum', 'Flag', 'IntEnum', 'IntFlag', 'StrEnum')
_PV = t.TypeVar('_PV', bound=MutableMapping)


class member_property(property, t.Generic[_PV, _MT]):

    __slots__ = ('name',)

    def __init__(self, fget=None, fset=None, fdel=None, doc=None) -> None:
        super().__init__(fget=fget, fset=fset, fdel=fdel, doc=doc)
        self.name = None if fget is None else fget.__name__

    def __set_name__(self, owner, name):
        if self.name == (self.fget and self.fget.__name__ or None):
            self.name = name
        elif name != self.name:
            raise TypeError(
                "Cannot assign the same member_property to two different names "
                f"({self.name!r} and {name!r})."
            )

    def __get__(self, obj:  t.Optional[_MT], type: t.Optional[type[_MT]]) -> _PV:
        if obj is None:
            return self
        elif self.fget is None:
            return getattr(type.__member_data__[obj.name], self.name)
        return super().__get__(obj, type=type)


class _MemberData:
    def __post_init__(self):
        if self._name is not None and self.label is None:
            object.__setattr__(self, 'label', _humanize(self._name).title()) 



class EnumMeta(BaseEnumMeta):

    def __new__(mcs, name, bases, attrs, *, fields=None, frozen=True, **kwds):

        get_member_names = \
              lambda d=None, f=list, *, a=attrs: _get_member_names(a, f, d)

        if fields is None and '__properties__' in attrs:
            warnings.warn(
                f'ClassVar __properties__ in {name}. '
                f'New syntax:  class {name}('
                f'{", ".join(b.__name__ for b in bases)}, '
                f'fields={attrs["__properties__"]!r}, defaults=`prop defaults`)', 
                DeprecationWarning, 
                stacklevel=2
            )
            
            if '__property_defaults__' in attrs:
                raise AttributeError(
                    f'{name}.__property_defaults__ no longer suppoted. '
                    f'Use the new syntax.'
                )

            fields = attrs.pop('__properties__')


        # if fields is not None:
        dcls = attrs['__member_dataclass__'] = mcs._define_member_dataclass(name, bases, fields, frozen=frozen is not False)

        data = attrs['__member_data__'] = {}

        mnames = get_member_names(False, [])
        
        for i in range(len(mnames)):
            mname = mnames[i]	
            value = attrs.get(mname)
            if fields and isinstance(value, tuple):
                value, *fargs = value
                attrs.update({mname:value})
            else:
                fargs = ()
            
            data[mname] = dcls(*fargs, _name=mname)
            
        for f in dataclass_fields(dcls):	
            if f.name not in {'_name', '_value'}:
                attrs.setdefault(f.name, member_property())
        
        cls = BaseEnumMeta.__new__(mcs, name, bases, attrs)
        return cls

    def __init__(self, name: str, bases: tuple[type, ...], namespace: dict[str, t.Any], **kwds) -> None:
        super().__init__(name, bases, namespace)
        self.__enum_ready__()

    @classmethod
    def __prepare__(mcls, name, bases, **kwds) -> None: 
        rv = super().__prepare__(name, bases)
        return rv

    @classmethod
    def _define_member_dataclass(mcls, name, bases, fieldset=None, *, frozen=True, **kwds) -> type[tuple]:
        
        fields: Iterable = ()

        mapfn = lambda f: (
            (f, t.Any, field(default=None))
                if isinstance(f, str)
                else (f.name, f.type, f)
                if isinstance(f, Field) 
                else chain(f := [*f], [t.Any, field(default=None)][len(f)-1:])
            )
        
        if is_dataclass(fieldset):
            dbase = fieldset
        elif isinstance(fieldset, str):
            dbase = make_dataclass(
                    f'_{name}DataclassAbc',
                    map(mapfn, re.sub(r'\s+', ' ', fieldset.replace(',', ' ').strip()).split()),
                    frozen=frozen
                )
        else:
            dbase = make_dataclass(
                    f'_{name}DataclassAbc',
                    map(mapfn, fieldset or ()),
                    frozen=frozen
                )

        ebase = bases[-1] if bases else None
        if issubclass(ebase, BaseEnum) and hasattr(ebase, '__member_dataclass__'):
            skip = dict((f.name, f) for f in dataclass_fields(dbase))
            skipfn = lambda f: f.name not in skip
            fields = map(mapfn, filter(skipfn, dataclass_fields(ebase.__member_dataclass__)))
        else:
            fields = [
                ('label', str, field(default=None)),
                ('_name', str, field(default=None)),
            ]

        return make_dataclass(
                f'_{name}Dataclass', 
                fields, 
                bases=(dbase, _MemberData), 
                frozen=frozen
            )

    def _choices_(cls):
        empty = ((None, cls.__empty__),) if hasattr(cls, '__empty__') else ()
        return empty + tuple((m._value_, m.label) for m in cls)

    choices = _choices_

    def __enum_ready__(cls):
        ...

    @property
    def __values__(cls):
        """
        Returns a mapping of values value->member.

        Note that this is a read-only view of the internal mapping.
        """
        return MappingProxyType(cls._value2member_map_)


# def _generate_next_value_(name, start, count, last_values):
#     max(start, *(v for v in last_values ))
#     if last_values:
#         last = last_values[-1]
#     else:
#         return start
#     if isinstance()

@export()
class Enum(BaseEnum, metaclass=EnumMeta):
    __slots__ = ()

    name: str
    label: str
    value: t.Any



@export()
class Flag(BaseFlag, metaclass=EnumMeta):
    __slots__ = ()

    name: str
    label: str
    value: int

    def __repr__(self) -> str:
        b = f"{{:0>{_bit_width(self.__class__)}}}".format(f'{abs(self._value_):b}')
        return f'<b{b!r}: {super().__repr__()}>'
    


@export()
@Set.register
class BitSetFlag(BaseFlag, metaclass=EnumMeta):
    """Behaves like a composite Set of it's composing atomic members.
    """

    __slots__ = ()

    name: str
    label: str
    value: int

    @classmethod
    def _make(cls, value):
        typ = type(value)
        if issubclass(typ, Collection) and not issubclass(typ, str):
            value = cls._compose(value)
        return cls(value)

    @classmethod
    def __enum_ready__(cls):
        extra = []
        pure = [m for m in cls if not m._is_composite or extra.append(m)]
        if extra:
            fmt = f'{{}}(b{{!r:0>{_bit_width(cls)}}}) in {{!r}}'
            missed = lambda m: int(m) ^ cls._compose(cls._decompose(m))

            if bad := [fmt.format(v,f'{abs(v):b}', m) for m in extra if (v := missed(m))]:
                raise TypeError(
                    f'some members in {cls.__qualname__} have missing bits: '
                    f'{", ".join(bad)}.'
                )
                
    @classmethod
    def _compose(cls, bits: Iterable, inital=0):
        return reduce(lambda a, b: a | int(b), bits, int(inital))

    @classmethod
    @cache
    def _decompose(cls, bits):
        members, extra = _decompose(cls, int(bits))
        if extra:
            raise ValueError(f"{bits!r} is not a valid {cls.__qualname__}")
        members = [_ for m in members for _ in (cls._decompose(m) if m._is_composite else [m])]
        members.sort(key=lambda m: m._value_, reverse=True)
        return frozenorderedset(members)

    @property
    @cache
    def _is_composite(self):
        return not _is_bit(int(self))

    def isdisjoint(self, other):
        'Return True if two sets have a null intersection.'
        if not isinstance(other, self.__class__):
            other = self.__class__(other)
        return (self._value_ & other._value_) == 0
    
    def __bool__(self):
        if self._is_composite:
            return not not self._decompose(self)
        else:
            return not not self._value_
    
    def __len__(self):
        if self._is_composite:
            return len(self._decompose(self))
        return 1
    
    def __iter__(self):
        if self._is_composite:
            yield from self._decompose(self)
        else:
            yield self

    def __index__(self) -> int:
        return int(self._value_)

    def __repr__(self) -> str:
        b = f"{{:0>{_bit_width(self.__class__)}}}".format(f'{abs(self._value_):b}')
        return f'<b{b!r}: {super().__repr__()}>'
 
    def __sub__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self & ~other

    # def __le__(self, other):
    #     if not isinstance(other, self.__class__):
    #         return NotImplemented
    #     elif len(self) > len(other):
    #         return False
    #     elif (self._value_ & other._value_) == self._value_:
    #         return True
        
    #     return False

    # def __lt__(self, other):
    #     if not isinstance(other, self.__class__):
    #         return NotImplemented
    #     return len(self) < len(other) and self.__le__(other)

    # def __gt__(self, other):
    #     if not isinstance(other, self.__class__):
    #         return NotImplemented
    #     return len(self) > len(other) and self.__ge__(other)

    # def __ge__(self, other):
    #     if not isinstance(other, self.__class__):
    #         return NotImplemented
    #     elif len(self) < len(other):
    #         return False
    #     elif (other._value_ & self._value_) == other._value_:
    #         return True
    #     return False


@export()
class IntEnum(BaseIntEnum, metaclass=EnumMeta):
    __slots__ = ()

    name: str
    label: str
    value: int


class BitInt(int):
    __slots__ = ()

    def __repr__(self) -> str:
        return f"b'{abs(self):b}' ({self:d})"


@export()
class IntFlag(BaseIntFlag, metaclass=EnumMeta):
    __slots__ = ()

    name: str
    label: str
    value: int

    def __repr__(self) -> str:
        b = f"{{:0>{_bit_width(self.__class__)}}}".format(f'{abs(self._value_):b}')
        return f'<b{b!r}: {super().__repr__()}>'
    


@export()
class StrEnum(str, Enum):
    __slots__ = ()

    name: str
    label: str
    value: str

    def _generate_next_value_(name, start, count, last_values):
        return name





@cache
def _is_bit(v: int):
    v = int(v)
    return v & (v-1) == 0
    
@cache
def _bit_width(cls: type[IntFlag]):
    return len(f'{sorted(cls._value2member_map_, reverse=True)[0]:b}')
    