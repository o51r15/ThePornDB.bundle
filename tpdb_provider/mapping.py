"""Translate ThePornDB scene payloads into Plex provider Metadata objects."""
import logging
import os
import re
import unicodedata

from .config import config
from . import tpdb

log = logging.getLogger(__name__)

# Plex metadata type ids
TYPE_MOVIE = 1

ID_REGEXES = [
    re.compile(r'\[(?:theporndbid|TPDBID)=(?P<id>[^\]]+)\]', re.IGNORECASE),
    re.compile(r'^https?://(?:api\.)?theporndb\.net/scenes/(?P<id>[^/?#]+)', re.IGNORECASE),
]

_RATING_KEY_SAFE = re.compile(r'[^A-Za-z0-9_-]')


def safe_rating_key(value):
    """Plex allows only ASCII letters, numbers, dashes and underscores."""
    return _RATING_KEY_SAFE.sub('-', str(value or ''))


def guid_for(rating_key):
    return '%s://movie/%s' % (config.identifier, rating_key)


def key_for(rating_key):
    return '/library/metadata/%s' % rating_key


def levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1,
                               current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def cleanup_title(text):
    """Apply the user's filename cleanup regexes (old filepath_cleanup pref)."""
    if not text:
        return ''
    if config.cleanup_enable and config.cleanup_regex:
        for pattern in config.cleanup_regex.split(','):
            if not pattern:
                continue
            try:
                text = re.sub(pattern, config.cleanup_replace, text,
                              flags=re.IGNORECASE)
            except re.error as exc:
                log.warning('bad cleanup regex %r: %s', pattern, exc)
        text = ' '.join(text.split())
    return text


def extract_id(text):
    for regex in ID_REGEXES:
        found = regex.search(text or '')
        if found:
            return found.group('id')
    return None


def build_query(hints):
    """Work out what to search for, from a match request's hints."""
    title = (hints.get('title') or '').strip()
    filename = hints.get('filename') or ''

    if filename and (config.match_by_filename or not title):
        candidate = filename
        if config.strip_path:
            candidate = os.path.basename(candidate)
            candidate = candidate.rsplit('.', 1)[0]
        candidate = cleanup_title(candidate)
        if candidate:
            title = candidate

    if not title:
        return ''

    year = hints.get('year')
    if year and str(year) not in title:
        return '%s %s' % (title, year)
    return title


def _ascii(value):
    if value is None:
        return ''
    return unicodedata.normalize('NFKD', u'%s' % value).encode('ascii', 'ignore').decode('ascii')


def _site_of(scene):
    site = scene.get('site')
    return site if isinstance(site, dict) else {}


def _performer_entries(scene):
    roles = []
    for order, performer in enumerate(scene.get('performers') or [], 1):
        if not isinstance(performer, dict):
            continue
        parent = performer.get('parent') if isinstance(performer.get('parent'), dict) else None
        name = (parent or {}).get('name') or performer.get('name')
        thumb = (parent or {}).get('face') or performer.get('face')
        if not name:
            continue
        entry = {'tag': name, 'role': performer.get('name') or name, 'order': order}
        if thumb:
            entry['thumb'] = thumb
        roles.append(entry)
    return roles


def _image_url(scene, group, *sizes):
    block = scene.get(group)
    if isinstance(block, dict):
        for size in sizes:
            if block.get(size):
                return block[size]
    elif isinstance(block, str):
        return block
    return None


def collections_for(scene):
    """Site / parent / network / tag collections, as the old agent built them."""
    site = _site_of(scene)
    if not site:
        return []

    names = []
    site_name = site.get('name')
    site_id = site.get('id')

    if site_name and config.collections_from_site:
        names.append(config.collection_site_prefix + site_name)

    def resolve(block_key, other_id, prefix, enabled):
        if not enabled or not other_id or other_id == site_id:
            return
        block = site.get(block_key)
        name = block.get('name') if isinstance(block, dict) else None
        if not name:
            fetched = tpdb.get_site(other_id)
            name = (fetched or {}).get('name')
        if name and name != site_name:
            names.append(prefix + name)

    resolve('parent', site.get('parent_id') or site.get('network_id'),
            config.collection_parent_prefix, config.collections_from_parents)
    resolve('network', site.get('network_id'),
            config.collection_network_prefix, config.collections_from_networks)

    if config.collections_from_tags:
        names.extend(genres_for(scene))

    # de-duplicate, preserve order
    seen = set()
    result = []
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def genres_for(scene):
    genres = []
    for tag in scene.get('tags') or []:
        name = tag.get('name') if isinstance(tag, dict) else tag
        if name and name not in genres:
            genres.append(name)
    return genres


def apply_custom_title(title, roles, studio, collections):
    if not config.custom_title_enable:
        return title
    data = {
        'title': title or '',
        'actors': ', '.join(_ascii(r['tag']) for r in roles),
        'studio': _ascii(studio),
        'series': ', '.join(sorted({_ascii(c) for c in collections
                                    if not studio or c not in studio})),
    }
    try:
        return config.custom_title.format(**data)
    except (KeyError, IndexError, ValueError) as exc:
        log.warning('custom title format failed: %s', exc)
        return title


def to_match(scene, query, index):
    """A lightweight Metadata object for POST /library/metadata/matches."""
    rating_key = safe_rating_key(scene.get('id'))
    site = _site_of(scene)
    site_name = site.get('name') or ''
    title = scene.get('title') or scene.get('name') or ''
    date = scene.get('date') or ''
    year = None
    if date[:4].isdigit():
        year = int(date[:4])

    display = ('%s %s' % (site_name, title)).strip() if site_name else title

    item = {
        'ratingKey': rating_key,
        'key': key_for(rating_key),
        'guid': guid_for(rating_key),
        'type': 'movie',
        'title': display,
        'score': score_for(scene, query, index, title, site_name, date),
    }
    if year:
        item['year'] = year
    if date:
        item['originallyAvailableAt'] = date[:10]
    if site_name:
        item['studio'] = site_name
    if scene.get('description'):
        item['summary'] = scene['description']

    poster = _image_url(scene, 'posters', 'large', 'medium', 'small')
    if poster:
        item['thumb'] = poster
    art = _image_url(scene, 'background', 'full', 'large')
    if art:
        item['art'] = art

    return item


def score_for(scene, query, index, title, site_name, date):
    if config.score_method == 'custom' and query:
        try:
            formatted = config.custom_score.format(
                title=title, site=site_name, date=date)
        except (KeyError, IndexError, ValueError):
            formatted = title
        distance = levenshtein(' '.join(query.split()).lower(),
                               ' '.join(formatted.split()).lower())
        return max(0, 100 - distance)
    return max(0, 100 - index)


def to_metadata(scene):
    """The full Metadata object for GET /library/metadata/{ratingKey}."""
    rating_key = safe_rating_key(scene.get('id'))
    site = _site_of(scene)
    studio = site.get('name') or ''
    date = scene.get('date') or ''

    roles = _performer_entries(scene)
    genres = genres_for(scene)
    collections = collections_for(scene)

    title = scene.get('title') or scene.get('name') or ''
    title = apply_custom_title(title, roles, studio, collections)

    item = {
        'ratingKey': rating_key,
        'key': key_for(rating_key),
        'guid': guid_for(rating_key),
        'type': 'movie',
        'title': title,
        'contentRating': config.content_rating,
    }

    if scene.get('description'):
        item['summary'] = scene['description']
    if studio:
        item['studio'] = studio
    if date:
        item['originallyAvailableAt'] = date[:10]
        if date[:4].isdigit():
            item['year'] = int(date[:4])

    try:
        duration = int(scene.get('duration') or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration > 0:
        item['duration'] = duration * 1000

    images = []
    poster = _image_url(scene, 'posters', 'large', 'medium', 'small')
    if poster:
        item['thumb'] = poster
        images.append({'type': 'coverPoster', 'url': poster, 'alt': title})
    art = _image_url(scene, 'background', 'full', 'large')
    if art:
        item['art'] = art
        images.append({'type': 'background', 'url': art, 'alt': title})
    if images:
        item['Image'] = images

    if genres:
        item['Genre'] = [{'tag': g} for g in genres]
    if roles:
        item['Role'] = roles
    if collections:
        item['Collection'] = [{'tag': c} for c in collections]

    trailer = scene.get('trailer')
    if trailer:
        item['Extras'] = [{
            'type': 'trailer',
            'title': 'Trailer',
            'url': trailer,
            'thumb': art or poster or '',
        }]

    return item
