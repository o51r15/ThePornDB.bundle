"""Self-check: proves the upstream contract matches what mapping.py expects.

The TPDB API needs a token for every call, so field names can only be
validated once a real key is configured. This endpoint does that in one
request and reports exactly which expected fields are missing.
"""
from .config import config
from . import mapping, tpdb

# Fields mapping.py reads. dotted = nested. '[]' = list of objects.
SEARCH_FIELDS = ['id', 'title', 'date', 'site', 'site.id', 'site.name',
                 'site.network_id', 'posters', 'background']

SCENE_FIELDS = ['id', 'title', 'description', 'date', 'duration',
                'site', 'site.id', 'site.name', 'site.network_id',
                'performers', 'tags', 'posters', 'background', 'trailer']

LIST_ITEM_FIELDS = {
    'performers': ['name', 'face'],
    'tags': ['name'],
}


def _dig(obj, path):
    cur = obj
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _check(obj, fields):
    present, missing, empty = [], [], []
    for path in fields:
        found, value = _dig(obj, path)
        if not found:
            missing.append(path)
        elif value in (None, '', [], {}):
            empty.append(path)
        else:
            present.append(path)
    return {'present': present, 'missing': missing, 'nullOrEmpty': empty}


def _check_list(obj, key, subfields):
    items = obj.get(key)
    if not isinstance(items, list) or not items:
        return {'count': 0, 'note': 'no items to inspect'}
    first = items[0]
    if not isinstance(first, dict):
        return {'count': len(items), 'note': 'items are not objects'}
    return {
        'count': len(items),
        'keys': sorted(first.keys()),
        'fields': _check(first, subfields),
    }


def run(query):
    report = {
        'identifier': config.identifier,
        'apiKeyConfigured': bool(config.api_key),
        'query': query,
    }

    if not config.api_key:
        report['status'] = 'error'
        report['error'] = 'TPDB_API_KEY is not set'
        return report

    results = tpdb.search_scenes(query)
    report['search'] = {'resultCount': len(results)}

    if not results:
        report['status'] = 'error'
        report['error'] = ('No search results. Either the token is invalid '
                           '(check container logs for an upstream 401) or the '
                           'query matched nothing.')
        return report

    first = results[0]
    report['search']['topLevelKeys'] = sorted(first.keys())
    report['search']['fields'] = _check(first, SEARCH_FIELDS)

    scene_id = first.get('id')
    scene = tpdb.get_scene(scene_id)
    if not scene:
        report['status'] = 'error'
        report['error'] = 'Search worked but fetching scene %r failed' % scene_id
        return report

    report['scene'] = {
        'id': scene_id,
        'topLevelKeys': sorted(scene.keys()),
        'fields': _check(scene, SCENE_FIELDS),
    }
    for key, subfields in LIST_ITEM_FIELDS.items():
        report['scene'][key] = _check_list(scene, key, subfields)

    for group in ('posters', 'background'):
        block = scene.get(group)
        if isinstance(block, dict):
            report['scene'][group + 'Sizes'] = sorted(block.keys())
        elif block:
            report['scene'][group + 'Sizes'] = 'plain string url'

    # Prove the mapping end to end.
    report['mapped'] = {
        'match': mapping.to_match(first, query, 0),
        'metadata': mapping.to_metadata(scene),
    }

    missing = (report['search']['fields']['missing']
               + report['scene']['fields']['missing'])
    report['missingFields'] = missing
    report['status'] = 'ok' if not missing else 'fields-missing'
    if missing:
        report['hint'] = ('mapping.py expects these upstream fields but the API '
                          'did not return them - field names need updating.')
    return report
