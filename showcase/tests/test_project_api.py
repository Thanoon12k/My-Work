"""Offline tests for the opt-in portfolio API (python -m unittest discover)."""
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from showcase.project_api import register


class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = str(Path(self.tmp.name) / 'custom.json')
        self.base = [{
            'slug': 'existing', 'title': 'Original', 'en': '', 'desc': 'Old',
            'cat': 'web', 'stack': ['Flask'], 'repo': 'https://github.com/x/y',
            'live_url': '', 'featured': 10, 'hidden': False,
            'imgs': [{'src': 'img/existing/00.webp', 'kind': 'repo'}],
            'updated': '2026-01-01',
        }]
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True

        def custom():
            if os.path.isfile(self.file):
                with open(self.file, encoding='utf-8') as f:
                    return json.load(f)
            return {'projects': {}}

        def merged(include_hidden=False):
            changes = custom()['projects']
            result = []
            for base in self.base:
                p = dict(base)
                o = changes.get(p['slug'], {})
                for key in ('title', 'en', 'desc', 'cat', 'stack', 'repo',
                            'live_url', 'featured', 'hidden'):
                    if key in o and o[key] not in (None, ''):
                        p[key] = o[key]
                p['imgs'] = o.get('uploads', []) + p.get('imgs', [])
                result.append(p)
            for slug, o in changes.items():
                if o.get('new'):
                    p = dict(slug=slug, title=slug, en='', desc='', cat='web',
                             stack=[], repo='', live_url='', featured=99,
                             hidden=False, updated='', imgs=o.get('uploads', []))
                    p.update({k: v for k, v in o.items() if k in p and v is not None})
                    result.append(p)
            return result if include_hidden else [
                p for p in result if not p['hidden'] and p['imgs']]

        def save(path, value):
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(value, f)

        def fake_image(slug, f):
            if not f.filename.endswith('.png'):
                raise ValueError('invalid image')
            return {'src': 'u/%s/test.webp' % slug,
                    'thumb': 'u/%s/test_t.webp' % slug,
                    'kind': 'upload'}

        register(self.app, lock=threading.Lock(), data_file=self.file,
                 base_projects=lambda: self.base, custom=custom, merged=merged,
                 save=save, store_image=fake_image,
                 categories=['web', 'mobile', 'desktop'])
        self.client = self.app.test_client()
        self.auth = {'Authorization': 'Bearer strong-testing-token'}
        env = patch.dict(os.environ, {'SHOWCASE_API_TOKEN': 'strong-testing-token'})
        env.start()
        self.addCleanup(env.stop)

    def test_token_required_and_compact_list(self):
        self.assertEqual(self.client.get('/api/v1/projects').status_code, 401)
        r = self.client.get('/api/v1/projects?fields=slug,title', headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['projects'], [{'slug': 'existing', 'title': 'Original'}])
        self.assertEqual(r.json['total'], 1)
        self.assertEqual(r.headers['Cache-Control'], 'no-store')

    def test_patch_is_partial_with_precondition(self):
        url = '/api/v1/projects/existing'
        res = self.client.get(url, headers=self.auth)
        etag = res.headers['ETag']
        patch_headers = {**self.auth, 'If-Match': etag}
        changed = self.client.patch(url, headers=patch_headers,
                                    json={'desc': 'New description'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json['changed'], ['desc'])
        after = self.client.get(url, headers=self.auth)
        self.assertEqual(after.json['project']['title'], 'Original')
        self.assertEqual(after.json['project']['desc'], 'New description')
        self.assertEqual(self.client.patch(url, headers=patch_headers,
                                          json={'desc': 'Conflict'}).status_code, 412)
        self.assertEqual(self.client.patch(url, headers=self.auth,
                                          json={'desc': None}).status_code, 200)
        self.assertEqual(self.client.get(url, headers=self.auth).json[
            'project']['desc'], 'Old')

    def test_create_image_and_delete(self):
        url = '/api/v1/projects'
        r = self.client.post(url, headers=self.auth, json={
            'slug': 'new-one', 'title': 'New', 'cat': 'mobile'})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.json['visible'])
        img = self.client.post(url + '/new-one/images', headers=self.auth,
                               data={'image': (io.BytesIO(b'placeholder'), 'demo.png')})
        self.assertEqual(img.status_code, 201)
        detail = self.client.get(url + '/new-one?fields=slug,imgs',
                                 headers=self.auth)
        self.assertEqual(len(detail.json['project']['imgs']), 1)
        self.assertEqual(self.client.delete(url + '/new-one',
                                            headers=self.auth).status_code, 200)
        self.assertEqual(self.client.get(url + '/new-one',
                                         headers=self.auth).status_code, 404)

    def test_safety_errors(self):
        self.assertEqual(self.client.delete('/api/v1/projects/existing',
                                            headers=self.auth).status_code, 409)
        self.assertEqual(self.client.patch('/api/v1/projects/existing',
                                           headers=self.auth,
                                           json={'cat': 'nonsense'}).status_code, 400)
        self.assertEqual(self.client.patch('/api/v1/projects/existing',
                                           headers=self.auth,
                                           json={'repo': 'javascript:alert(1)'}).status_code, 400)
        self.assertEqual(self.client.patch('/api/v1/projects/existing',
                                           headers=self.auth,
                                           json={'imgs': []}).status_code, 400)
        self.assertEqual(self.client.post('/api/v1/projects', headers=self.auth,
                                          json={'slug': '../bad', 'title': 'Bad'}
                                          ).status_code, 400)


if __name__ == '__main__':
    unittest.main()
