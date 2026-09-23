"""Plex custom metadata providers for ThePornDB (Scenes, Movies, JAV).

Implements the provider contract documented at
https://developer.plex.tv/pms/  (API Info -> Metadata Providers).
"""
import logging

from flask import Blueprint, Flask, jsonify, request

from .config import config
from . import mapping, selftest, tpdb, tv

log = logging.getLogger(__name__)

MOVIE = 1


def container(metadata, offset=0, total=None, identifier=None):
    items = metadata if isinstance(metadata, list) else [metadata]
    return jsonify({'MediaContainer': {
        'identifier': identifier or config.identifier,
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


def make_provider(name, identifier, title, kind):
    """One movie-type provider bound to a TPDB collection.

    The bundle shipped Scenes, Movies and JAV as three copies of the same
    agent differing only in the upstream path, so they are one factory here.
    """
    bp = Blueprint(name, __name__)

    def box(metadata, offset=0, total=None):
        return container(metadata, offset, total, identifier=identifier)

    @bp.route('', methods=['GET'])
    @bp.route('/', methods=['GET'])
    def manifest():
        """Provider root: the MediaProvider document PMS reads on registration."""
        return jsonify({'MediaProvider': {
            'identifier': identifier,
            'title': title,
            'version': config.version,
            'Types': [
                {'type': MOVIE, 'Scheme': [{'scheme': identifier}]},
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
            return box([])

        # An explicit guid, or a TPDB id embedded in the title/filename, is exact.
        scene_id = None
        guid = hints.get('guid') or ''
        if guid.startswith(identifier + '://'):
            scene_id = guid.rsplit('/', 1)[-1]
        if not scene_id:
            scene_id = (mapping.extract_id(hints.get('title'))
                        or mapping.extract_id(hints.get('filename')))

        if scene_id:
            scene = tpdb.get_scene(scene_id, kind=kind)
            if not scene:
                return box([])
            item = mapping.to_match(scene, '', 0, identifier)
            item['score'] = 100
            return box([item])

        query = mapping.build_query(hints)
        if not query:
            return box([])

        results = tpdb.search_scenes(
            query, kind=kind,
            oshash=hints.get('hash') or hints.get('openSubtitleHash'))
        start, size = paging()

        items = [mapping.to_match(scene, query, idx, identifier)
                 for idx, scene in enumerate(results) if isinstance(scene, dict)]
        items.sort(key=lambda i: i.get('score', 0), reverse=True)

        if not hints.get('manual'):
            items = items[:size]
        page = items[start:start + size]
        return box(page, offset=start, total=len(items))

    @bp.route('/library/metadata/<rating_key>', methods=['GET'])
    def metadata(rating_key):
        scene = tpdb.get_scene(rating_key, kind=kind,
                               add_to_collection=config.save_to_collection)
        if not scene:
            return jsonify({'error': 'not found'}), 404
        return box([mapping.to_metadata(scene, identifier)])

    @bp.route('/library/metadata/<rating_key>/images', methods=['GET'])
    def images(rating_key):
        scene = tpdb.get_scene(rating_key, kind=kind)
        if not scene:
            return jsonify({'error': 'not found'}), 404
        item = mapping.to_metadata(scene, identifier)
        return jsonify({'MediaContainer': {
            'identifier': identifier,
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
        return box([], total=0)

    @bp.route('/library/metadata/<rating_key>/children', methods=['GET'])
    @bp.route('/library/metadata/<rating_key>/grandchildren', methods=['GET'])
    def children(rating_key):
        # Movies have no children; the endpoints exist so PMS gets a clean answer.
        return box([], total=0)

    return bp


def create_app():
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    app = Flask(__name__)
    registered = {}

    app.register_blueprint(
        make_provider('scenes', config.identifier, config.title, 'scenes'),
        url_prefix='/scenes')
    registered['scenes'] = '/scenes'

    if config.movies_enable:
        app.register_blueprint(
            make_provider('movies', config.movies_identifier,
                          config.movies_title, 'movies'),
            url_prefix='/movies')
        registered['movies'] = '/movies'

    if config.jav_enable:
        app.register_blueprint(
            make_provider('jav', config.jav_identifier,
                          config.jav_title, 'jav'),
            url_prefix='/jav')
        registered['jav'] = '/jav'

    app.register_blueprint(tv.bp, url_prefix='/tv')
    registered['tv'] = '/tv'

    @app.route('/health')
    def health():
        return jsonify({
            'status': 'ok',
            'apiKeyConfigured': bool(config.api_key),
            'providers': registered,
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
