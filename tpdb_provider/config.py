"""Configuration, carried over from the old bundle's DefaultPrefs.json.

Everything is read from environment variables because the new metadata
provider API has no Plex-side preferences UI.
"""
import os


def _bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _str(name, default=''):
    val = os.environ.get(name)
    return default if val is None else val


class Config(object):
    # --- upstream ---
    api_base = _str('TPDB_API_BASE', 'https://api.theporndb.net')
    api_key = _str('TPDB_API_KEY')
    timeout = int(_str('TPDB_TIMEOUT', '30'))
    retries = int(_str('TPDB_RETRIES', '3'))
    cache_ttl = int(_str('TPDB_CACHE_TTL', '3600'))

    # --- provider identity ---
    identifier = _str('TPDB_IDENTIFIER', 'tv.plex.agents.custom.theporndb.scenes')
    title = _str('TPDB_TITLE', 'ThePornDB Scenes')
    version = _str('TPDB_VERSION', '2.0.0')

    # --- matching ---
    # 'default' = upstream relevance order, 'custom' = Levenshtein against a format string
    score_method = _str('TPDB_SCORE_METHOD', 'default')
    custom_score = _str('TPDB_CUSTOM_SCORE', '{site} {date} {title}')
    match_by_filename = _bool('TPDB_MATCH_BY_FILENAME', True)
    strip_path = _bool('TPDB_STRIP_PATH', True)
    cleanup_enable = _bool('TPDB_CLEANUP_ENABLE', False)
    cleanup_regex = _str('TPDB_CLEANUP_REGEX')
    cleanup_replace = _str('TPDB_CLEANUP_REPLACE')
    max_results = int(_str('TPDB_MAX_RESULTS', '20'))

    # --- metadata shaping ---
    content_rating = _str('TPDB_CONTENT_RATING', 'XXX')
    collections_from_site = _bool('TPDB_COLLECTIONS_FROM_SITE', True)
    collections_from_parents = _bool('TPDB_COLLECTIONS_FROM_PARENTS', True)
    collections_from_networks = _bool('TPDB_COLLECTIONS_FROM_NETWORKS', True)
    collections_from_tags = _bool('TPDB_COLLECTIONS_FROM_TAGS', False)
    collection_site_prefix = _str('TPDB_COLLECTION_SITE_PREFIX')
    collection_parent_prefix = _str('TPDB_COLLECTION_PARENT_PREFIX')
    collection_network_prefix = _str('TPDB_COLLECTION_NETWORK_PREFIX')
    custom_title_enable = _bool('TPDB_CUSTOM_TITLE_ENABLE', False)
    custom_title = _str('TPDB_CUSTOM_TITLE', '{actors} - {title} [{studio}/{series}]')
    save_to_collection = _bool('TPDB_SAVE_TO_COLLECTION', False)

    # --- tv provider (site = show, year = season, scene = episode) ---
    tv_identifier = _str('TPDB_TV_IDENTIFIER', 'tv.plex.agents.custom.theporndb.tv')
    tv_title = _str('TPDB_TV_TITLE', 'ThePornDB Scenes (TV)')
    max_site_pages = int(_str('TPDB_MAX_SITE_PAGES', '30'))
    site_fetch_workers = int(_str('TPDB_SITE_FETCH_WORKERS', '8'))

    # --- service ---
    log_level = _str('TPDB_LOG_LEVEL', 'INFO')


config = Config()
