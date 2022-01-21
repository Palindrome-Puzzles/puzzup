import time
import typing as t

KT = t.TypeVar('KT')
VT = t.TypeVar('VT')

Seconds = int


class TimedCache(t.Generic[KT, VT]):
    '''Simple cache where entries expire after some amount of time.'''
    timeout: Seconds
    _cache: dict[KT, tuple[VT, float]]  # pytype: disable=not-supported-yet

    def __init__(self, timeout: Seconds = 600):
        self.timeout = timeout
        self._cache = {}

    def set(self, key, item):
        self._cache[key] = (item, time.time() + self.timeout)

    def get(self, key):
        if key not in self._cache:
            return None
        item, expires = self._cache.get(key, (None, 0))
        if time.time() > expires:
            del self._cache[key]
            return None
        return item

    def has(self, key):
        return self.get(key) is not None

    def drop(self, key):
        if key in self._cache:
            del self._cache[key]
