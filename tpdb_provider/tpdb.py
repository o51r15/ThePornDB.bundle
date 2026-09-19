"""Thin client for the ThePornDB API."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .config import config

log = logging.getLogger(__name__)

_local = threading.local()
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


def _get_session():
    session = getattr(_local, 'session', None)
    if session is None:
        session = requests.Session()
        _local.session = session
    return session


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
            resp = _get_session().get(url, params=params,
                                      headers=_headers(),
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


def search_sites(query):
    """Site search. Only `q` actually filters - `search`/`parse` are ignored
    upstream and return the whole 103k-row site table."""
    body = get_json('/sites', {'q': query})
    if not body:
        return []
    return body.get('data') or []


def scenes_for_site(site_id, max_pages=None):
    """Every scene for a site, walking upstream pagination in parallel.

    Upstream accepts per_page up to 100 (200 returns nothing), which cuts a
    4000-scene site from 201 requests to 41. Page 1 is fetched first to learn
    last_page, then the rest go out concurrently - serial fetching measured
    ~36s wall time, almost all of it network wait, which Plex will not sit
    through.
    """
    if max_pages is None:
        max_pages = config.max_site_pages

    per_page = config.site_page_size
    first = get_json('/scenes', {'site_id': site_id, 'page': 1,
                                 'per_page': per_page})
    if not first:
        return []

    scenes = [s for s in (first.get('data') or []) if isinstance(s, dict)]

    meta = first.get('meta') or {}
    try:
        last = int(meta.get('last_page') or 1)
    except (TypeError, ValueError):
        last = 1
    last = min(last, max_pages)
    if last <= 1:
        return scenes

    pages = list(range(2, last + 1))
    bodies = {}
    workers = max(1, min(config.site_fetch_workers, len(pages)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(get_json, '/scenes',
                        {'site_id': site_id, 'page': p,
                         'per_page': per_page}): p
            for p in pages
        }
        for future in as_completed(futures):
            page = futures[future]
            try:
                bodies[page] = future.result()
            except Exception as exc:
                log.warning('page %d of site %s failed: %s', page, site_id, exc)
                bodies[page] = None

    # reassemble in page order so date sorting downstream is stable
    for page in pages:
        body = bodies.get(page)
        if not body:
            continue
        scenes.extend(s for s in (body.get('data') or [])
                      if isinstance(s, dict))

    return scenes
