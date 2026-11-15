"""Offline tests for the admin dashboard endpoints: ordering, image order, trash."""
import importlib
import json
import os
import sys
import tempfile
import unittest


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root, data = os.path.join(self.tmp.name, 'site'), os.path.join(self.tmp.name, 'data')
        os.makedirs(root)
        img = lambda s, n: {'src': 'img/%s/%02d.webp' % (s, n), 'kind': 'live'}
        base = [{'slug': s, 'title': s.upper(), 'en': '', 'desc': '', 'cat': 'web', 'stack': [],
                 'repo': '', 'featured': 99, 'imgs': [img(s, 0), img(s, 1), img(s, 2)]}
                for s in ('a', 'b', 'c')]
        json.dump(base, open(os.path.join(root, 'data.json'), 'w'))
        os.environ['SHOWCASE_ROOT'], os.environ['SHOWCASE_DATA'] = root, data
        sys.modules.pop('showcase.server', None)
        self.srv = importlib.import_module('showcase.server')
        self.client = self.srv.app.test_client()
        with self.client.session_transaction() as s:
            s['admin'], s['csrf'] = True, 'tok'

    def post(self, url, **kw):
        return self.client.post(url, headers={'X-CSRF': 'tok'}, **kw)

    def slugs(self):
        return [p['slug'] for p in self.srv.merged()]

    def test_needs_login(self):
        c = self.srv.app.test_client()
        self.assertEqual(c.post('/admin/api/order', json={'slugs': []}).status_code, 401)

    def test_project_order(self):
        self.assertEqual(self.post('/admin/api/order', json={'slugs': ['c', 'a', 'x']}).status_code, 200)
        self.assertEqual(self.slugs(), ['c', 'a', 'b'])     # unknown dropped, unlisted last

    def test_image_order(self):
        self.post('/admin/api/img_order', json={'slug': 'b', 'srcs': ['img/b/02.webp']})
        p = next(p for p in self.srv.merged() if p['slug'] == 'b')
        self.assertEqual(p['imgs'][0]['src'], 'img/b/02.webp')
        self.assertEqual(p['thumb'], 'img/b/02.webp')

    def test_trash_and_restore(self):
        self.assertTrue(self.post('/admin/api/delete', data={'slug': 'a'}).get_json()['trashed'])
        self.assertNotIn('a', self.slugs())
        self.post('/admin/api/restore', data={'slug': 'a'})
        self.assertIn('a', self.slugs())

    def test_bad_input(self):
        self.assertEqual(self.post('/admin/api/order', json={'slugs': 'a'}).status_code, 400)
        self.assertEqual(self.post('/admin/api/img_order',
                                   json={'slug': 'zz', 'srcs': []}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
