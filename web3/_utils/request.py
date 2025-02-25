from collections import (
    OrderedDict,
)
import os
import threading
from typing import (
    Any,
    Dict,
    Union,
)

from aiohttp import (
    ClientResponse,
    ClientSession,
    ClientTimeout,
)
from eth_typing import (
    URI,
)
import lru
import requests

from web3._utils.caching import (
    generate_cache_key,
)


class SessionCache:
    def __init__(self, size: int):
        self._size = size
        self._data: OrderedDict[str, Any] = OrderedDict()

    def cache(self, key: str, value: Any) -> Dict[str, Any]:
        evicted_items = None
        # If the key is already in the OrderedDict just update it
        # and don't evict any values. Ideally, we could still check to see
        # if there are too many items in the OrderedDict but that may rearrange
        # the order it should be unlikely that the size could grow over the limit
        if key not in self._data:
            while len(self._data) >= self._size:
                if evicted_items is None:
                    evicted_items = {}
                k, v = self._data.popitem(last=False)
                evicted_items[k] = v
        self._data[key] = value
        return evicted_items

    def get_cache_entry(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, item: str) -> bool:
        return item in self._data

    def __len__(self) -> int:
        return len(self._data)


def get_default_http_endpoint() -> URI:
    return URI(os.environ.get("WEB3_HTTP_PROVIDER_URI", "http://localhost:8545"))


def cache_session(endpoint_uri: URI, session: requests.Session) -> None:
    cache_key = generate_cache_key(endpoint_uri)
    _session_cache[cache_key] = session


def _remove_session(_key: str, session: requests.Session) -> None:
    session.close()


_session_cache = lru.LRU(8, callback=_remove_session)


def get_session(endpoint_uri: URI) -> requests.Session:
    cache_key = generate_cache_key(endpoint_uri)
    if cache_key not in _session_cache:
        _session_cache[cache_key] = requests.Session()
    return _session_cache[cache_key]


def get_response_from_get_request(
    endpoint_uri: URI, *args: Any, **kwargs: Any
) -> requests.Response:
    kwargs.setdefault("timeout", 10)
    session = get_session(endpoint_uri)
    response = session.get(endpoint_uri, *args, **kwargs)
    return response


def get_response_from_post_request(
    endpoint_uri: URI, *args: Any, **kwargs: Any
) -> requests.Response:
    kwargs.setdefault("timeout", 10)
    session = get_session(endpoint_uri)
    response = session.post(endpoint_uri, *args, **kwargs)
    return response


def make_post_request(
    endpoint_uri: URI, data: Union[bytes, Dict[str, Any]], *args: Any, **kwargs: Any
) -> bytes:
    response = get_response_from_post_request(endpoint_uri, data=data, *args, **kwargs)
    response.raise_for_status()
    return response.content


# --- async --- #

_async_session_cache_lock = threading.Lock()
_async_session_cache = SessionCache(size=20)


async def cache_async_session(endpoint_uri: URI, session: ClientSession) -> None:
    cache_key = generate_cache_key(endpoint_uri)
    with _async_session_cache_lock:
        evicted_items = _async_session_cache.cache(cache_key, session)
        if evicted_items is not None:
            for key, session in evicted_items.items():
                await session.close()


async def get_async_session(endpoint_uri: URI) -> ClientSession:
    cache_key = generate_cache_key(endpoint_uri)
    if cache_key not in _async_session_cache:
        await cache_async_session(endpoint_uri, ClientSession(raise_for_status=True))
    return _async_session_cache.get_cache_entry(cache_key)


async def async_get_response_from_get_request(
    endpoint_uri: URI, *args: Any, **kwargs: Any
) -> ClientResponse:
    kwargs.setdefault("timeout", ClientTimeout(10))
    session = await get_async_session(endpoint_uri)
    response = await session.get(endpoint_uri, *args, **kwargs)
    return response


async def async_get_response_from_post_request(
    endpoint_uri: URI, *args: Any, **kwargs: Any
) -> ClientResponse:
    kwargs.setdefault("timeout", ClientTimeout(10))
    session = await get_async_session(endpoint_uri)
    response = await session.post(endpoint_uri, *args, **kwargs)
    return response


async def async_make_post_request(
    endpoint_uri: URI, data: Union[bytes, Dict[str, Any]], *args: Any, **kwargs: Any
) -> bytes:
    response = await async_get_response_from_post_request(
        endpoint_uri, data=data, *args, **kwargs
    )
    return await response.read()


async def async_get_json_from_client_response(
    response: ClientResponse,
) -> Dict[str, Any]:
    return await response.json()
