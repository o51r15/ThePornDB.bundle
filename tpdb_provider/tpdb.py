"""Thin client for the ThePornDB API."""
import logging
import threading
import time

import requests

from .config import config

log = logging.getLogger(__name__)

_session = requests.Session()
_cache = {}
_cache_lock = threading.Lock()


def _cache_get(key):
    if config.cache_ttl <= 0:
        return None
    with _cache_lock:
        hit = _cache.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > config.cache_ttl:
        with _cache_lock:
            _cache.pop(key, None)
        return None
    return value


def _cache_put(key, value):
    if config.cache_ttl <= 0:
        return
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _headers():
    headers = {
        'User-Agent': 'tpdb-provider/%s' % config.version,
        'Accept': 'application/json',
    }
    if config.api_key:
        headers['Authorization'] = 'Bearer %s' % config.api_key
    return headers


def get_json(path, params=None):
    """GET an API path, returning the decoded body or None.

    Retries transient failures with a real backoff (the old bundle's
    `sleep_time * x` multiplied by zero on the first pass).
    """
    url = config.api_base.rstrip('/') + path
    cache_key = (url, tuple(sorted((params or {}).items())))

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    delay = 1.0
    last_error = None
    for attempt in range(1, config.retries + 1):
        try:
            resp = _session.get(url, params=params, headers=_headers(),
                                timeout=config.timeout)
        except requests.RequestException as exc:
            last_error = exc
            log.warning('request failed (attempt %d/%d) %s: %s',
                        attempt, config.retries, url, exc)
        else:
            if resp.status_code == 404:
                return None
            if resp.ok:
                try:
                    body = resp.json()
                except ValueError as exc:
                    log.error('non-JSON response from %s: %s', url, exc)
                    return None
                _cache_put(cache_key, body)
                return body
            # 4xx other than 404 will not improve on retry
            if 400 <= resp.status_code < 500:
                log.error('upstream %s for %s', resp.status_code, url)
                return None
            last_error = 'HTTP %s' % resp.status_code
            log.warning('upstream %s (attempt %d/%d) %s',
                        resp.status_code, attempt, config.retries, url)

        if attempt < config.retries:
            time.sleep(delay)
            delay *= 2

    log.error('giving up on %s: %s', url, last_error)
    return None


def search_scenes(query, oshash=None):
    params = {'parse': query}
    if oshash:
        params['hash'] = oshash
    body = get_json('/scenes', params)
    if not body:
        return []
    if body.get('error'):
        log.error('upstream error: %s', body['error'])
        return []
    return body.get('data') or []


def get_scene(scene_id, add_to_collection=False):
    params = {'add_to_collection': 1} if add_to_collection else None
    body = get_json('/scenes/%s' % scene_id, params)
    if not body:
        return None
    return body.get('data')


def get_site(site_id):
    body = get_json('/sites/%s' % site_id)
    if not body:
        return None
    return body.get('data')
