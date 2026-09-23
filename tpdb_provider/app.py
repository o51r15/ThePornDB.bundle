"""Plex custom metadata provider for ThePornDB (Scenes).

Implements the provider contract documented at
https://developer.plex.tv/pms/  (API Info -> Metadata Providers).
"""
import logging

from flask import Blueprint, Flask, jsonify, request

from .config import config
from . import mapping, selftest, tpdb, tv

log = logging.getLogger(__name__)

bp = Blueprint('scenes', __name__)

MOVIE = 1


def container(metadata, offset=0, total=None):
    items = metadata if isinstance(metadata, list) else [metadata]
    return jsonify({'MediaContainer': {
        'identifier': config.identifier,
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


@bp.route('', methods=['GET'])
@bp.route('/', methods=['GET'])
def manifest():
    """Provider root: the MediaProvider document PMS reads on registration."""
    return jsonify({'MediaProvider': {
        'identifier': config.identifier,
        'title': config.title,
        'version': config.version,
        'Types': [
            {'type': MOVIE, 'Scheme': [{'scheme': config.identifier}]},
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

    log.debug('match hints: %s', hints)

    if hints.get('type') and str(hints['type']) != str(MOVIE):
        return container([])

    # An explicit guid, or a TPDB id embedded in the title/filename, is exact.
    scene_id = None
    guid = hints.get('guid') or ''
    if guid.startswith(config.identifier + '://'):
        scene_id = guid.rsplit('/', 1)[-1]
    if not scene_id:
        scene_id = (mapping.extract_id(hints.get('title'))
                    or mapping.extract_id(hints.get('filename')))

    if scene_id:
        scene = tpdb.get_scene(scene_id)
        if not scene:
            return container([])
        item = mapping.to_match(scene, '', 0)
        item['score'] = 100
        return container([item])

    query = mapping.build_query(hints)
    if not query:
        return container([])

    results = tpdb.search_scenes(
        query, oshash=hints.get('hash') or hints.get('openSubtitleHash'))
    start, size = paging()

    items = [mapping.to_match(scene, query, idx)
             for idx, scene in enumerate(results) if isinstance(scene, dict)]
    items.sort(key=lambda i: i.get('score', 0), reverse=True)

    if not hints.get('manual'):
        items = items[:size]
    page = items[start:start + size]
    return container(page, offset=start, total=len(items))


@bp.route('/library/metadata/<rating_key>', methods=['GET'])
def metadata(rating_key):
    scene = tpdb.get_scene(rating_key,
                           add_to_collection=config.save_to_collection)
    if not scene:
        return jsonify({'error': 'not found'}), 404
    return container([mapping.to_metadata(scene)])


@bp.route('/library/metadata/<rating_key>/images', methods=['GET'])
def images(rating_key):
    scene = tpdb.get_scene(rating_key)
    if not scene:
        return jsonify({'error': 'not found'}), 404
    item = mapping.to_metadata(scene)
    return jsonify({'MediaContainer': {
        'identifier': config.identifier,
        'size': len(item.get('Image', [])),
        'Image': item.get('Image', []),
    }})


@bp.route('/selftest', methods=['GET'])
def selftest_route():
    """Validate the upstream contract with a real API call."""
    query = request.args.get('q') or 'Brazzers'
    report = selftest.run(query)
    code = 200 if report.get('status') == 'ok' else 503
    return jsonify(report), code


@bp.route('/library/metadata/<rating_key>/extras', methods=['GET'])
def extras(rating_key):
    return container([], total=0)


@bp.route('/library/metadata/<rating_key>/children', methods=['GET'])
@bp.route('/library/metadata/<rating_key>/grandchildren', methods=['GET'])
def children(rating_key):
    # Movies have no children; the endpoints exist so PMS gets a clean answer.
    return container([], total=0)


def create_app():
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix='/scenes')
    app.register_blueprint(tv.bp, url_prefix='/tv')

    @app.route('/health')
    def health():
        return jsonify({
            'status': 'ok',
            'provider': config.identifier,
            'apiKeyConfigured': bool(config.api_key),
            'providers': {
                'movies': '/scenes',
                'tv': '/tv',
            },
            'selftest': '/scenes/selftest?q=<title>',
        })

    @app.errorhandler(400)
    def bad_request(err):
        return jsonify({'error': 'bad request'}), 400

    @app.errorhandler(500)
    def server_error(err):
        log.exception('unhandled error')
        return jsonify({'error': 'internal error'}), 500

    if not config.api_key:
        log.warning('TPDB_API_KEY is not set - upstream requests will fail')

    return app
