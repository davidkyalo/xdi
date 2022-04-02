import typing as t

import pytest
from xdi import Dep
from xdi.providers import DepMarkerProvider as Provider

from .abc import ProviderTestCase

xfail = pytest.mark.xfail
parametrize = pytest.mark.parametrize


_Ta = t.TypeVar("_Ta")
_Tx = t.TypeVar("_Tx")


class DepMarkerTests(ProviderTestCase):
    @pytest.fixture
    def provider(self, marker):
        return Provider(marker)

    @pytest.fixture
    def marker(self):
        return Dep(_Tx, default=Dep(_Ta))

    @pytest.fixture
    def context(self, context, value_setter):
        context[_Ta] = value_setter
        return context


class DepMarkerDataPathTests(DepMarkerTests):
    @pytest.fixture
    def marker(self):
        return Dep(_Ta).bar.run(1, 2, 3, k1=1, k2=2).a["list"][2:-2]

    @pytest.fixture
    def value_factory(self):
        return Foo

    @pytest.fixture
    def value_setter(self, value_factory, marker: Dep):
        def fn(*a, **kw):
            val = value_factory(*a, **kw)
            self.value = marker.__eval__(val)
            return val

        return fn


class DepMarkerOnlySelfTests(DepMarkerTests):
    @pytest.fixture
    def marker(self):
        return Dep(_Tx, injector=Dep.ONLY_SELF, default=Dep(_Ta))

    @pytest.fixture
    def injector(self, injector, Injector):
        return Injector(injector)

    @pytest.fixture
    def context(self, context, injector, value_setter):
        context[_Ta] = value_setter
        context.parent[_Tx] = lambda: (value_setter(), object())
        return context


class DepMarkerSkipSelfTests(DepMarkerTests):
    @pytest.fixture
    def marker(self):
        return Dep(_Tx, injector=Dep.SKIP_SELF)

    @pytest.fixture
    def injector(self, injector, Injector):
        return Injector(injector)

    @pytest.fixture
    def context(self, context, injector, value_setter):
        context.parent[_Tx] = value_setter
        context[_Tx] = lambda: (value_setter(), object())
        return context


class Foo:
    a = dict(list=list(range(10)), data=dict(bee="Im a bee"))

    class bar:
        @classmethod
        def run(cls, *args, **kwargs) -> None:
            print(f"ran with({args=}, {kwargs=})")
            return Foo
