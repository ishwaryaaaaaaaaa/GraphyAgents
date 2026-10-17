import itertools

import pytest

from agent import store

_n = itertools.count()


@pytest.fixture
def user():
    u = f"t{next(_n)}"
    store.reset(u)
    yield u
    store.reset(u)
