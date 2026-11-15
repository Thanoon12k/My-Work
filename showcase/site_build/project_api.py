"""Small token-efficient JSON API for the existing portfolio storage.

Opt-in: put a strong token in SHOWCASE_API_TOKEN or private portfolio_data/api_token.
All routes require Authorization: Bearer <token>, including reads.
"""
import hashlib
import hmac
import json
import os
import re
import shutil
import time
from urllib.parse import urlsplit

from flask import jsonify, request

FIELDS = ('slug', 'title', 'en', 'desc', 'cat', 'stack', 'repo', 'live_url',
          'featured', 'hidden', 'imgs', 'updated')
EDITABLE = set(FIELDS) - {'slug', 'imgs', 'updated'}
DEFAULT_LIST = ('slug', 'title', 'cat')
DEFAULT_DETAIL = ('slug', 'title', 'en', 'desc', 'cat', 'stack', 'repo',
                  'live_url', 'featured', 'hidden')


def register(app, *, lock, data_file, base_projects, custom, merged, save,
             store_image, categories):
    """Add API routes; share the admin's lock and durable custom.json."""
    token_file = os.path.join(os.path.dirname(data_file), 'api_token')

    def reply(payload, status=200, **headers):
        r = jsonify(payload)
        r.status_code = status
        r.headers['Cache-Control'] = 'no-store'
        for k, v in headers.items():
            r.headers[k] = v
        return r

    def auth_error():
        expected = os.environ.get('SHOWCASE_API_TOKEN', '').strip()
        if not expected:
            try:
                with open(token_file, encoding='utf-8') as f:
                    expected = f.read().strip()
            except OSError:
                pass
        if not expected:
            return reply({'error': 'api_disabled'}, 503)
        auth = request.headers.get('Authorization', '')
        got = auth[7:] if auth.startswith('Bearer ') else ''
        if len(got) > 512 or not hmac.compare_digest(got, expected):
            return reply({'error': 'unauthorized'}, 401,
                         **{'WWW-Authenticate': 'Bearer'})
        return None

    def select_fields(default):
        val = request.args.get('fields', '')
        chosen = tuple(x.strip() for x in val.split(',')) if val else default
        if not chosen or any(x not in FIELDS for x in chosen):
            raise ValueError('invalid fields')
        return chosen

    def project(slug):
        return next((p for p in merged(include_hidden=True)
                     if p['slug'] == slug), None)

    def fingerprint(p):
        s = json.dumps({k: p.get(k) for k in FIELDS}, ensure_ascii=False,
                       sort_keys=True, separators=(',', ':'))
        return '"' + hashlib.sha256(s.encode()).hexdigest()[:16] + '"'

    def valid_patch(data):
        if not isinstance(data, dict) or not data:
            raise ValueError('expected non-empty JSON object')
        unknown = set(data) - EDITABLE
        if unknown:
            raise ValueError('unknown fields: ' + ','.join(sorted(unknown)))
        out = {}
        for k, v in data.items():
            if v is None:
                out[k] = None  # remove override; restore built-in value
            elif k in ('title', 'en', 'desc'):
                cap = 3000 if k == 'desc' else 160
                if not isinstance(v, str) or len(v) > cap:
                    raise ValueError('invalid ' + k)
                out[k] = v.strip()
            elif k in ('repo', 'live_url'):
                if not isinstance(v, str) or len(v) > 1000:
                    raise ValueError('invalid ' + k)
                if v:
                    u = urlsplit(v)
                    if u.scheme not in ('https', 'http') or not u.hostname or u.username:
                        raise ValueError('invalid URL: ' + k)
                out[k] = v
            elif k == 'cat':
                if v not in categories:
                    raise ValueError('invalid category')
                out[k] = v
            elif k == 'stack':
                if not isinstance(v, list) or len(v) > 8 or any(
                    not isinstance(x, str) or not x.strip() or len(x) > 60 for x in v
                ):
                    raise ValueError('stack must be a list of up to 8 short strings')
                out[k] = v
            elif k == 'featured':
                if type(v) is not int or not 0 <= v <= 9999:
                    raise ValueError('featured must be an integer 0..9999')
                out[k] = v
            elif k == 'hidden':
                if type(v) is not bool:
                    raise ValueError('hidden must be boolean')
                out[k] = v
        return out

    @app.route('/api/v1/projects', methods=['GET', 'POST'])
    def portable_projects():
        err = auth_error()
        if err is not None:
            return err
        if request.method == 'GET':
            try:
                fields = select_fields(DEFAULT_LIST)
                limit = int(request.args.get('limit', '100'))
                offset = int(request.args.get('offset', '0'))
                if not 1 <= limit <= 100 or offset < 0:
                    raise ValueError('invalid pagination')
            except (ValueError, TypeError) as ex:
                return reply({'error': str(ex)}, 400)
            q = request.args.get('q', '').strip().casefold()[:100]
            entries = merged(include_hidden=True)
            if q:
                entries = [p for p in entries if q in p['slug'].casefold()
                           or q in str(p.get('title', '')).casefold()]
            page = entries[offset:offset + limit]
            return reply({'projects': [{k: p.get(k) for k in fields}
                                        for p in page],
                          'total': len(entries)})
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return reply({'error': 'expected JSON object'}, 400)
        slug = data.get('slug')
        if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,62}', slug):
            return reply({'error': 'slug must be 2-63 lowercase letters, digits or -'}, 400)
        try:
            values = valid_patch({k: v for k, v in data.items() if k != 'slug'})
        except ValueError as ex:
            return reply({'error': str(ex)}, 400)
        if not values.get('title'):
            return reply({'error': 'title required'}, 400)
        with lock:
            c = custom()
            known = {p['slug'] for p in base_projects()} | set(c['projects'])
            if slug in known:
                return reply({'error': 'already_exists'}, 409)
            c['projects'][slug] = {'new': True,
                                   'created': time.strftime('%Y-%m-%d'),
                                   **{k: v for k, v in values.items()
                                      if v is not None}}
            save(data_file, c)
        return reply({'ok': True, 'slug': slug, 'visible': False,
                      'next': 'POST /api/v1/projects/' + slug + '/images'}, 201)

    @app.route('/api/v1/projects/<slug>', methods=['GET', 'PATCH', 'DELETE'])
    def portable_project(slug):
        err = auth_error()
        if err is not None:
            return err
        if request.method == 'GET':
            try:
                fields = select_fields(DEFAULT_DETAIL)
            except ValueError as ex:
                return reply({'error': str(ex)}, 400)
            p = project(slug)
            if p is None:
                return reply({'error': 'not_found'}, 404)
            return reply({'project': {k: p.get(k) for k in fields}},
                         ETag=fingerprint(p))
        with lock:
            p = project(slug)
            if p is None:
                return reply({'error': 'not_found'}, 404)
            old_etag = fingerprint(p)
            if request.headers.get('If-Match') and request.headers['If-Match'] != old_etag:
                return reply({'error': 'stale', 'current_etag': old_etag}, 412)
            c = custom()
            if request.method == 'DELETE':
                if not c['projects'].get(slug, {}).get('new'):
                    return reply({'error': 'built_in_project_use_PATCH_hidden_true'}, 409)
                del c['projects'][slug]
                save(data_file, c)
                # Only API-created slugs match this pattern; guard the storage path.
                if re.fullmatch(r'[a-z0-9][a-z0-9-]{1,62}', slug):
                    base = os.path.join(os.path.dirname(data_file), 'uploads')
                    shutil.rmtree(os.path.join(base, slug), ignore_errors=True)
                return reply({'ok': True, 'slug': slug})
            data = request.get_json(silent=True)
            try:
                changes = valid_patch(data)
            except ValueError as ex:
                return reply({'error': str(ex)}, 400)
            row = c['projects'].setdefault(slug, {})
            for key, value in changes.items():
                if value is None:
                    row.pop(key, None)
                else:
                    row[key] = value
            save(data_file, c)
        return reply({'ok': True, 'slug': slug, 'changed': sorted(changes)})

    @app.route('/api/v1/projects/<slug>/images', methods=['POST'])
    def portable_project_image(slug):
        err = auth_error()
        if err is not None:
            return err
        image = request.files.get('image')
        if not image or not image.filename:
            return reply({'error': 'multipart image required'}, 400)
        with lock:
            if project(slug) is None:
                return reply({'error': 'not_found'}, 404)
            try:
                meta = store_image(slug, image)
            except ValueError as ex:
                return reply({'error': str(ex)}, 400)
            c = custom()
            c['projects'].setdefault(slug, {}).setdefault('uploads', []).append(meta)
            save(data_file, c)
        return reply({'ok': True, 'slug': slug, 'image': meta['src']}, 201)
