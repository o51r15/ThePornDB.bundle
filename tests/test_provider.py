import json, os, sys, unittest
from unittest import mock

os.environ.update({
    'TPDB_API_KEY': 'test-key',
    'TPDB_CACHE_TTL': '0',
    'TPDB_COLLECTIONS_FROM_TAGS': 'true',
    'TPDB_COLLECTION_SITE_PREFIX': 'Site: ',
})
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from tpdb_provider import create_app
from tpdb_provider import tpdb, mapping

SCENE = {
    'id': '0a1b2c3d-4e5f-6789-abcd-ef0123456789',
    'title': 'The Test Scene',
    'description': 'A description.',
    'date': '2023-04-05 00:00:00',
    'duration': 1800,
    'site': {'id': 10, 'name': 'TestSite', 'network_id': 20, 'parent_id': 30,
             'network': {'name': 'TestNetwork'}},
    'tags': [{'name': 'Tag A'}, {'name': 'Tag B'}],
    'performers': [
        {'name': 'Stage Name', 'face': 'http://img/face1.jpg',
         'parent': {'name': 'Real Name', 'face': 'http://img/face2.jpg'}},
        {'name': 'Solo Performer', 'face': 'http://img/face3.jpg'},
    ],
    'posters': {'large': 'http://img/poster.jpg'},
    'background': {'full': 'http://img/bg.jpg'},
    'trailer': 'http://video/trailer.mp4',
}

SEARCH = [dict(SCENE, id='id-%d' % i, title='Result %d' % i) for i in range(5)]


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app().test_client()

    def test_manifest(self):
        r = self.app.get('/scenes')
        self.assertEqual(r.status_code, 200)
        mp = r.get_json()['MediaProvider']
        self.assertTrue(mp['identifier'].startswith('tv.plex.agents.custom.'))
        self.assertEqual(mp['Types'][0]['type'], 1)
        feats = {f['type']: f['key'] for f in mp['Feature']}
        self.assertEqual(feats['metadata'], '/library/metadata')
        self.assertEqual(feats['match'], '/library/metadata/matches')
        self.assertRegex(mp['identifier'].split('tv.plex.agents.custom.')[1],
                         r'^[a-zA-Z0-9.]+$')

    def test_matches_by_title(self):
        with mock.patch.object(tpdb, 'search_scenes', return_value=SEARCH) as m:
            r = self.app.post('/scenes/library/metadata/matches',
                              json={'type': 1, 'title': 'Result 1', 'year': 2023})
        self.assertEqual(r.status_code, 200)
        mc = r.get_json()['MediaContainer']
        self.assertEqual(mc['size'], 5)
        first = mc['Metadata'][0]
        self.assertEqual(first['guid'],
                         '%s://movie/%s' % (mapping.config.identifier, first['ratingKey']))
        self.assertEqual(first['key'], '/library/metadata/' + first['ratingKey'])
        self.assertEqual(first['type'], 'movie')
        self.assertRegex(first['ratingKey'], r'^[A-Za-z0-9_-]+$')
        self.assertEqual(m.call_args[0][0], 'Result 1 2023')
        scores = [i['score'] for i in mc['Metadata']]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_matches_by_filename(self):
        with mock.patch.object(tpdb, 'search_scenes', return_value=SEARCH) as m:
            self.app.post('/scenes/library/metadata/matches',
                          json={'type': 1,
                                'filename': '/media/x/TestSite 2023-04-05 The Test Scene.mp4'})
        self.assertEqual(m.call_args[0][0], 'TestSite 2023-04-05 The Test Scene')

    def test_matches_by_embedded_id(self):
        with mock.patch.object(tpdb, 'get_scene', return_value=SCENE) as m:
            r = self.app.post('/scenes/library/metadata/matches',
                              json={'type': 1,
                                    'filename': 'Whatever [TPDBID=abc-123].mp4'})
        self.assertEqual(m.call_args[0][0], 'abc-123')
        mc = r.get_json()['MediaContainer']
        self.assertEqual(mc['size'], 1)
        self.assertEqual(mc['Metadata'][0]['score'], 100)

    def test_matches_wrong_type(self):
        r = self.app.post('/scenes/library/metadata/matches', json={'type': 2, 'title': 'x'})
        self.assertEqual(r.get_json()['MediaContainer']['size'], 0)

    def test_matches_pagination(self):
        with mock.patch.object(tpdb, 'search_scenes', return_value=SEARCH):
            r = self.app.post('/scenes/library/metadata/matches',
                              json={'type': 1, 'title': 'x', 'manual': 1},
                              headers={'X-Plex-Container-Start': '2',
                                       'X-Plex-Container-Size': '2'})
        mc = r.get_json()['MediaContainer']
        self.assertEqual((mc['offset'], mc['size'], mc['totalSize']), (2, 2, 5))

    def test_metadata(self):
        with mock.patch.object(tpdb, 'get_scene', return_value=SCENE), \
             mock.patch.object(tpdb, 'get_site', return_value={'name': 'TestParent'}):
            r = self.app.get('/scenes/library/metadata/' + SCENE['id'])
        self.assertEqual(r.status_code, 200)
        item = r.get_json()['MediaContainer']['Metadata'][0]
        self.assertEqual(item['title'], 'The Test Scene')
        self.assertEqual(item['studio'], 'TestSite')
        self.assertEqual(item['contentRating'], 'XXX')
        self.assertEqual(item['originallyAvailableAt'], '2023-04-05')
        self.assertEqual(item['year'], 2023)
        self.assertEqual(item['duration'], 1800000)
        self.assertEqual([g['tag'] for g in item['Genre']], ['Tag A', 'Tag B'])
        roles = item['Role']
        self.assertEqual(roles[0]['tag'], 'Real Name')
        self.assertEqual(roles[0]['role'], 'Stage Name')
        self.assertEqual(roles[0]['thumb'], 'http://img/face2.jpg')
        self.assertEqual(roles[0]['order'], 1)
        self.assertEqual(roles[1]['tag'], 'Solo Performer')
        cols = [c['tag'] for c in item['Collection']]
        self.assertIn('Site: TestSite', cols)
        self.assertIn('TestParent', cols)
        self.assertIn('TestNetwork', cols)
        self.assertIn('Tag A', cols)
        types = {i['type']: i['url'] for i in item['Image']}
        self.assertEqual(types['coverPoster'], 'http://img/poster.jpg')
        self.assertEqual(types['background'], 'http://img/bg.jpg')
        self.assertEqual(item['Extras'][0]['url'], 'http://video/trailer.mp4')

    def test_metadata_404(self):
        with mock.patch.object(tpdb, 'get_scene', return_value=None):
            r = self.app.get('/scenes/library/metadata/nope')
        self.assertEqual(r.status_code, 404)

    def test_metadata_sparse_payload(self):
        sparse = {'id': 99, 'title': 'Bare'}
        with mock.patch.object(tpdb, 'get_scene', return_value=sparse):
            r = self.app.get('/scenes/library/metadata/99')
        item = r.get_json()['MediaContainer']['Metadata'][0]
        self.assertEqual(item['title'], 'Bare')
        self.assertNotIn('Role', item)
        self.assertNotIn('duration', item)

    def test_images_and_children(self):
        with mock.patch.object(tpdb, 'get_scene', return_value=SCENE), \
             mock.patch.object(tpdb, 'get_site', return_value=None):
            r = self.app.get('/scenes/library/metadata/x/images')
            c = self.app.get('/scenes/library/metadata/x/children')
        self.assertEqual(r.get_json()['MediaContainer']['size'], 2)
        self.assertEqual(c.get_json()['MediaContainer']['totalSize'], 0)

    def test_custom_title_and_cleanup(self):
        cfg = mapping.config
        old = (cfg.custom_title_enable, cfg.cleanup_enable, cfg.cleanup_regex)
        cfg.custom_title_enable = True
        cfg.cleanup_enable = True
        cfg.cleanup_regex = r'\[.*?\],\(.*?\)'
        try:
            self.assertEqual(mapping.cleanup_title('Site (1080p) [XXX] Title'),
                             'Site Title')
            with mock.patch.object(tpdb, 'get_scene', return_value=SCENE), \
                 mock.patch.object(tpdb, 'get_site', return_value=None):
                r = self.app.get('/scenes/library/metadata/x')
            title = r.get_json()['MediaContainer']['Metadata'][0]['title']
            self.assertIn('Real Name, Solo Performer', title)
            self.assertIn('The Test Scene', title)
        finally:
            (cfg.custom_title_enable, cfg.cleanup_enable, cfg.cleanup_regex) = old

    def test_levenshtein_and_health(self):
        self.assertEqual(mapping.levenshtein('kitten', 'sitting'), 3)
        self.assertEqual(mapping.levenshtein('', 'abc'), 3)
        self.assertEqual(self.app.get('/health').get_json()['status'], 'ok')

class HashTest(unittest.TestCase):
    """Regression: Plex puts its own hash in every match request. Forwarding it
    made TPDB reject the whole call with
    422 {"message":"The hash must be valid hash."} - 4222 times in one scan,
    so every single file came back unmatched."""

    def setUp(self):
        self.app = create_app().test_client()

    def _hash_sent(self, payload, oshash_enable=False):
        seen = {}
        def fake(path, params=None):
            seen.update(params or {})
            return {'data': []}
        old = tpdb.config.oshash_enable
        tpdb.config.oshash_enable = oshash_enable
        try:
            with mock.patch.object(tpdb, 'get_json', side_effect=fake):
                self.app.post('/scenes/library/metadata/matches', json=payload)
        finally:
            tpdb.config.oshash_enable = old
        return seen

    def test_plex_hash_is_never_forwarded_by_default(self):
        sent = self._hash_sent({'type': 1, 'title': 'x',
                                'hash': '5d7768244de0ee001fcc7fed'})
        self.assertNotIn('hash', sent)

    def test_junk_hash_rejected_even_when_enabled(self):
        for bad in ('abc123', '', 'not-a-hash', '5d7768244de0ee001fcc7fed'):
            sent = self._hash_sent({'type': 1, 'title': 'x', 'hash': bad},
                                   oshash_enable=True)
            self.assertNotIn('hash', sent, 'forwarded bad hash %r' % bad)

    def test_real_oshash_forwarded_when_enabled(self):
        sent = self._hash_sent({'type': 1, 'title': 'x',
                                'hash': '8e245d9679d31e12'}, oshash_enable=True)
        self.assertEqual(sent.get('hash'), '8e245d9679d31e12')

    def test_real_oshash_still_suppressed_when_disabled(self):
        sent = self._hash_sent({'type': 1, 'title': 'x',
                                'hash': '8e245d9679d31e12'})
        self.assertNotIn('hash', sent)

class MoviesProviderTest(unittest.TestCase):
    """The bundle shipped Scenes, Movies and JAV as three copies of one agent
    differing only in the upstream path. Same factory here - so the thing worth
    testing is that each provider hits its own TPDB collection and stamps its
    own identifier."""

    def setUp(self):
        self.app = create_app().test_client()

    def _kind_used(self, prefix):
        seen = {}
        def fake(path, params=None):
            seen['path'] = path
            return {'data': []}
        with mock.patch.object(tpdb, 'get_json', side_effect=fake):
            self.app.post(prefix + '/library/metadata/matches',
                          json={'type': 1, 'title': 'anything'})
        return seen.get('path')

    def test_each_provider_queries_its_own_collection(self):
        self.assertEqual(self._kind_used('/scenes'), '/scenes')
        self.assertEqual(self._kind_used('/movies'), '/movies')

    def test_movies_manifest_is_its_own_provider(self):
        scenes = self.app.get('/scenes').get_json()['MediaProvider']
        movies = self.app.get('/movies').get_json()['MediaProvider']
        self.assertNotEqual(scenes['identifier'], movies['identifier'])
        self.assertTrue(movies['identifier'].startswith('tv.plex.agents.custom.'))
        self.assertEqual(movies['title'], 'ThePornDB Movies')
        self.assertEqual(movies['Types'][0]['type'], 1)
        self.assertEqual(movies['Types'][0]['Scheme'][0]['scheme'],
                         movies['identifier'])

    def test_movie_guids_carry_the_movies_identifier(self):
        movie = {'id': 'mv-1', 'title': 'Some Feature', 'date': '2014-05-06',
                 'description': 'd', 'duration': 7200,
                 'site': {'id': 1, 'name': 'Studio'},
                 'performers': [], 'tags': [],
                 'posters': {'large': 'http://img/p.jpg'},
                 'background': {'full': 'http://img/b.jpg'}}
        with mock.patch.object(tpdb, 'get_scene', return_value=movie):
            m = self.app.get('/movies/library/metadata/mv-1').get_json()
        item = m['MediaContainer']['Metadata'][0]
        self.assertTrue(item['guid'].startswith(
            'tv.plex.agents.custom.theporndb.movies://movie/'))
        self.assertEqual(m['MediaContainer']['identifier'],
                         'tv.plex.agents.custom.theporndb.movies')
        self.assertEqual(item['title'], 'Some Feature')
        self.assertEqual(item['duration'], 7200000)

    def test_movies_metadata_fetch_uses_movies_path(self):
        seen = {}
        def fake(path, params=None):
            seen['path'] = path
            return {'data': {'id': 'x', 'title': 't'}}
        with mock.patch.object(tpdb, 'get_json', side_effect=fake):
            self.app.get('/movies/library/metadata/x')
        self.assertEqual(seen['path'], '/movies/x')

    def test_jav_is_off_by_default(self):
        self.assertEqual(self.app.get('/jav').status_code, 404)

    def test_health_lists_the_live_providers(self):
        providers = self.app.get('/health').get_json()['providers']
        self.assertEqual(providers.get('scenes'), '/scenes')
        self.assertEqual(providers.get('movies'), '/movies')
        self.assertEqual(providers.get('tv'), '/tv')
        self.assertNotIn('jav', providers)


if __name__ == '__main__':
    unittest.main(verbosity=2)
