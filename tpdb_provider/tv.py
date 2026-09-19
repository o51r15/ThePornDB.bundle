"""TV-shaped provider: TPDB site = show, year = season, scene = episode.

Plex requires a TV provider to serve types 2, 3 and 4 together, so this
module owns all three plus the children/grandchildren endpoints.

Rating keys are prefixed so one metadata endpoint can dispatch on them:
    show-<siteId>            e.g. show-92
    season-<siteId>-<year>   e.g. season-92-2019
    ep-<sceneUuid>           e.g. ep-c0e5cc64-...
"""
import logging
import os
import re

from flask import Blueprint, jsonify, request

from .config import config
from . import mapping, tpdb

log = logging.getLogger(__name__)

bp = Blueprint('tv', __name__)

SHOW, SEASON, EPISODE = 2, 3, 4

DATE_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
# scene-release naming: BrandNewAmateurs.24.02.02.Keyton.Keem...
DOTTED_DATE_RE = re.compile(r'(?<!\d)(\d{2})\.(\d{2})\.(\d{2})(?!\d)')


# --------------------------------------------------------------- keys / guids

def show_key(site_id):
    return 'show-%s' % mapping.safe_rating_key(site_id)


def season_key(site_id, year):
    return 'season-%s-%s' % (mapping.safe_rating_key(site_id), year)


def episode_key(scene_id):
    return 'ep-%s' % mapping.safe_rating_key(scene_id)


def parse_key(rating_key):
    """-> (kind, site_id|scene_id, year|None)"""
    if rating_key.startswith('season-'):
        rest = rating_key[len('season-'):]
        site_id, _, year = rest.rpartition('-')
        return 'season', site_id, year
    if rating_key.startswith('show-'):
        return 'show', rating_key[len('show-'):], None
    if rating_key.startswith('ep-'):
        return 'episode', rating_key[len('ep-'):], None
    return None, None, None


def guid(kind, rating_key):
    return '%s://%s/%s' % (config.tv_identifier, kind, rating_key)


def key_path(rating_key):
    return '/library/metadata/%s' % rating_key


# ------------------------------------------------------------------- helpers

def year_of(scene):
    date = scene.get('date') or ''
    return date[:4] if date[:4].isdigit() else None


def episode_index(scene):
    """Episode number derived from the air date: 2019-01-25 -> 125.

    TPDB scenes carry no episode number, so the date is the only stable
    ordering key. Unique within a site-year except for same-day releases on
    the same site, which stay distinct by GUID.
    """
    found = DATE_RE.search(scene.get('date') or '')
    if not found:
        return None
    return int(found.group(2)) * 100 + int(found.group(3))


def _site_image(site, *keys):
    for key in keys:
        value = site.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            for size in ('full', 'large', 'medium', 'small'):
                if value.get(size):
                    return value[size]
    return None


# ------------------------------------------------------------------- mapping

def site_to_show(site):
    site_id = site.get('id')
    rating_key = show_key(site_id)
    title = site.get('name') or site.get('short_name') or ''

    item = {
        'ratingKey': rating_key,
        'key': key_path(rating_key),
        'guid': guid('show', rating_key),
        'type': 'show',
        'title': title,
        'contentRating': config.content_rating,
    }
    if site.get('description'):
        item['summary'] = site['description']

    network = site.get('network')
    if isinstance(network, dict) and network.get('name'):
        item['studio'] = network['name']
    elif site.get('url'):
        item['studio'] = title

    images = []
    poster = _site_image(site, 'poster', 'logo', 'favicon')
    if poster:
        item['thumb'] = poster
        images.append({'type': 'coverPoster', 'url': poster, 'alt': title})
    art = _site_image(site, 'background', 'poster')
    if art:
        item['art'] = art
        images.append({'type': 'background', 'url': art, 'alt': title})
    if images:
        item['Image'] = images

    return item


def make_season(site, year, episode_count=None):
    site_id = site.get('id')
    rating_key = season_key(site_id, year)
    parent_rk = show_key(site_id)
    site_name = site.get('name') or ''

    item = {
        'ratingKey': rating_key,
        'key': key_path(rating_key),
        'guid': guid('season', rating_key),
        'type': 'season',
        'title': 'Season %s' % year,
        'index': int(year),
        'year': int(year),
        'parentRatingKey': parent_rk,
        'parentKey': key_path(parent_rk),
        'parentGuid': guid('show', parent_rk),
        'parentTitle': site_name,
        'parentType': 'show',
        'contentRating': config.content_rating,
    }
    if episode_count is not None:
        item['leafCount'] = episode_count

    poster = _site_image(site, 'poster', 'logo')
    if poster:
        item['thumb'] = poster
    return item


def scene_to_episode(scene, site=None):
    scene_id = scene.get('id')
    rating_key = episode_key(scene_id)

    site = site or (scene.get('site') if isinstance(scene.get('site'), dict) else {})
    site_id = site.get('id') or scene.get('site_id')
    site_name = site.get('name') or ''
    year = year_of(scene)
    date = scene.get('date') or ''

    item = {
        'ratingKey': rating_key,
        'key': key_path(rating_key),
        'guid': guid('episode', rating_key),
        'type': 'episode',
        'title': scene.get('title') or scene.get('name') or '',
        'contentRating': config.content_rating,
    }

    index = episode_index(scene)
    if index is not None:
        item['index'] = index
    if date:
        item['originallyAvailableAt'] = date[:10]
    if year:
        item['year'] = int(year)
        item['parentIndex'] = int(year)

    if scene.get('description'):
        item['summary'] = scene['description']

    try:
        duration = int(scene.get('duration') or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration > 0:
        item['duration'] = duration * 1000

    if site_id is not None:
        gp_rk = show_key(site_id)
        item['grandparentRatingKey'] = gp_rk
        item['grandparentKey'] = key_path(gp_rk)
        item['grandparentGuid'] = guid('show', gp_rk)
        item['grandparentTitle'] = site_name
        gp_thumb = _site_image(site, 'poster', 'logo')
        if gp_thumb:
            item['grandparentThumb'] = gp_thumb
        if year:
            p_rk = season_key(site_id, year)
            item['parentRatingKey'] = p_rk
            item['parentKey'] = key_path(p_rk)
            item['parentGuid'] = guid('season', p_rk)
            item['parentTitle'] = 'Season %s' % year
            item['parentType'] = 'season'
    if site_name:
        item['studio'] = site_name

    images = []
    poster = mapping._image_url(scene, 'posters', 'large', 'medium', 'small')
    if poster:
        item['thumb'] = poster
        images.append({'type': 'coverPoster', 'url': poster, 'alt': item['title']})
    art = mapping._image_url(scene, 'background', 'full', 'large')
    if art:
        item['art'] = art
        images.append({'type': 'background', 'url': art, 'alt': item['title']})
    if images:
        item['Image'] = images

    genres = mapping.genres_for(scene)
    if genres:
        item['Genre'] = [{'tag': g} for g in genres]

    roles = mapping._performer_entries(scene)
    if roles:
        item['Role'] = roles

    return item


# -------------------------------------------------------------------- routing

def container(items, offset=0, total=None):
    return jsonify({'MediaContainer': {
        'identifier': config.tv_identifier,
        'size': len(items),
        'totalSize': len(items) if total is None else total,
        'offset': offset,
        'Metadata': items,
    }})


def paging():
    """Plex sends X-Plex-Container-Start/Size as QUERY PARAMETERS on GETs,
    not as headers. Reading only headers made every children page return the
    same first slice, so Plex walked 0..580 and got identical bodies back."""
    def _int(name, default):
        raw = request.args.get(name)
        if raw is None:
            raw = request.headers.get(name)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    start = max(0, _int('X-Plex-Container-Start', 0))
    size = _int('X-Plex-Container-Size', config.max_results)
    return start, max(1, min(size, config.max_page_size))


def _resolve_site(name):
    """Best site match for a show title."""
    if not name:
        return None
    sites = tpdb.search_sites(name)
    if not sites:
        return None
    wanted = ' '.join(name.split()).lower()
    for site in sites:
        if (site.get('name') or '').lower() == wanted:
            return site
    for site in sites:
        if (site.get('short_name') or '').lower() == wanted.replace(' ', ''):
            return site
    return sites[0]


def _hint_date(hints):
    for key in ('date', 'originallyAvailableAt', 'title', 'filename'):
        found = DATE_RE.search(str(hints.get(key) or ''))
        if found:
            return found.group(0)
    # release naming carries the date as YY.MM.DD
    found = DOTTED_DATE_RE.search(str(hints.get('filename') or ''))
    if found:
        yy, mm, dd = found.groups()
        if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
            return '20%s-%s-%s' % (yy, mm, dd)
    return None


def _hint_year(hints):
    """Which of our year-seasons the request is really about.

    Plex sends index=<year> only when the filename carries S<year>E<n>.
    Otherwise its scanner falls back to season 1, so we recover the year
    from whatever date is in the filename.
    """
    try:
        index = int(hints.get('index'))
    except (TypeError, ValueError):
        index = None
    if index and index > 1900:
        return str(index)
    date = _hint_date(hints)
    return date[:4] if date else None


def _hint_wants_children(hints):
    return str(hints.get('includeChildren') or '') in ('1', 'true', 'True')


@bp.route('', methods=['GET'])
@bp.route('/', methods=['GET'])
def manifest():
    schemes = [{'scheme': config.tv_identifier}]
    return jsonify({'MediaProvider': {
        'identifier': config.tv_identifier,
        'title': config.tv_title,
        'version': config.version,
        'Types': [
            {'type': SHOW, 'Scheme': schemes},
            {'type': SEASON, 'Scheme': schemes},
            {'type': EPISODE, 'Scheme': schemes},
        ],
        'Feature': [
            {'type': 'metadata', 'key': '/library/metadata'},
            {'type': 'match', 'key': '/library/metadata/matches'},
        ],
    }})


@bp.route('/library/metadata/matches', methods=['POST'])
def matches():
    hints = request.get_json(silent=True) or {}
    if not hints:
        hints = request.form.to_dict() or request.args.to_dict()

    log.debug('[tv] match hints: %s', hints)

    try:
        mtype = int(hints.get('type') or 0)
    except (TypeError, ValueError):
        mtype = 0

    if mtype == SHOW:
        return _match_show(hints)
    if mtype == SEASON:
        return _match_season(hints)
    if mtype == EPISODE:
        return _match_episode(hints)
    return container([])


def _match_show(hints):
    title = (hints.get('title') or '').strip()
    if not title and hints.get('filename'):
        title = os.path.basename(hints['filename'].rstrip('/'))
    title = mapping.cleanup_title(title)
    if not title:
        return container([])

    sites = tpdb.search_sites(title)
    start, size = paging()
    wanted = ' '.join(title.split()).lower()

    items = []
    for idx, site in enumerate(sites):
        if not isinstance(site, dict):
            continue
        item = site_to_show(site)
        name = (site.get('name') or '').lower()
        if name == wanted:
            item['score'] = 100
        else:
            item['score'] = max(
                0, 95 - mapping.levenshtein(wanted, name) - idx)
        items.append(item)

    items.sort(key=lambda i: i.get('score', 0), reverse=True)
    if not hints.get('manual'):
        items = items[:size]
    return container(items[start:start + size], offset=start, total=len(items))


def _match_season(hints):
    name = hints.get('parentTitle') or hints.get('title') or ''
    site = _resolve_site(mapping.cleanup_title(name))
    if not site:
        return container([])

    year = _hint_year(hints)
    if not year:
        return container([])

    item = make_season(site, year)
    item['score'] = 100
    # Plex sends includeChildren=1 on the season match and binds its files to
    # whatever children come back - it never sends a type=4 episode match.
    if _hint_wants_children(hints):
        item['Children'] = _episodes_for(site, site.get('id'), year)
    return container([item])


def _match_episode(hints):
    site_name = (hints.get('grandparentTitle')
                 or hints.get('parentTitle') or '')
    site_name = mapping.cleanup_title(site_name)
    date = _hint_date(hints)
    title = mapping.cleanup_title(hints.get('title') or '')

    terms = [t for t in (site_name, date, title) if t]
    if not terms:
        if hints.get('filename'):
            terms = [mapping.build_query({'filename': hints['filename']})]
        if not terms or not terms[0]:
            return container([])

    query = ' '.join(terms)
    log.debug('[tv] episode query: %r', query)
    results = tpdb.search_scenes(query)

    if not results and date and site_name:
        results = tpdb.search_scenes('%s %s' % (site_name, date))

    start, size = paging()
    items = []
    for idx, scene in enumerate(results):
        if not isinstance(scene, dict):
            continue
        item = scene_to_episode(scene)
        scene_date = (scene.get('date') or '')[:10]
        if date and scene_date == date:
            item['score'] = 100
        else:
            item['score'] = max(0, 90 - idx)
        items.append(item)

    items.sort(key=lambda i: i.get('score', 0), reverse=True)
    if not hints.get('manual'):
        items = items[:size]
    return container(items[start:start + size], offset=start, total=len(items))


def _wants_children():
    return str(request.args.get('includeChildren') or '') in ('1', 'true')


def _seasons_for(site, site_id):
    scenes = tpdb.scenes_for_site(site_id)
    counts = {}
    for scene in scenes:
        scene_year = year_of(scene)
        if scene_year:
            counts[scene_year] = counts.get(scene_year, 0) + 1
    return [make_season(site, y, counts[y]) for y in sorted(counts)]


def _episodes_for(site, site_id, year=None):
    scenes = tpdb.scenes_for_site(site_id)
    if year is not None:
        scenes = [s for s in scenes if year_of(s) == str(year)]
    scenes.sort(key=lambda s: s.get('date') or '')
    return [scene_to_episode(s, site) for s in scenes]


@bp.route('/library/metadata/<rating_key>', methods=['GET'])
def metadata(rating_key):
    kind, ident, year = parse_key(rating_key)

    if kind == 'show':
        site = tpdb.get_site(ident)
        if not site:
            return jsonify({'error': 'not found'}), 404
        item = site_to_show(site)
        if _wants_children():
            # Plex asks for the show with includeChildren=1 and expects the
            # seasons inline. Returning the bare show made Plex treat it as
            # having no seasons, so nothing underneath could ever match.
            item['Children'] = _seasons_for(site, ident)
        return container([item])

    if kind == 'season':
        site = tpdb.get_site(ident)
        if not site:
            return jsonify({'error': 'not found'}), 404
        item = make_season(site, year)
        if _wants_children():
            item['Children'] = _episodes_for(site, ident, year)
        return container([item])

    if kind == 'episode':
        scene = tpdb.get_scene(ident)
        if not scene:
            return jsonify({'error': 'not found'}), 404
        return container([scene_to_episode(scene)])

    return jsonify({'error': 'unrecognised rating key'}), 404


@bp.route('/library/metadata/<rating_key>/children', methods=['GET'])
def children(rating_key):
    kind, ident, year = parse_key(rating_key)
    start, size = paging()

    if kind == 'show':
        site = tpdb.get_site(ident)
        if not site:
            return jsonify({'error': 'not found'}), 404
        seasons = _seasons_for(site, ident)
        return container(seasons[start:start + size], offset=start,
                         total=len(seasons))

    if kind == 'season':
        site = tpdb.get_site(ident)
        episodes = _episodes_for(site, ident, year)
        return container(episodes[start:start + size], offset=start,
                         total=len(episodes))

    return container([], total=0)


@bp.route('/library/metadata/<rating_key>/extras', methods=['GET'])
def extras(rating_key):
    # Plex asks every show for extras; an empty container beats a 404.
    return container([], total=0)


@bp.route('/library/metadata/<rating_key>/grandchildren', methods=['GET'])
def grandchildren(rating_key):
    kind, ident, _ = parse_key(rating_key)
    start, size = paging()

    if kind != 'show':
        return container([], total=0)

    site = tpdb.get_site(ident)
    episodes = _episodes_for(site, ident)
    return container(episodes[start:start + size], offset=start,
                     total=len(episodes))
