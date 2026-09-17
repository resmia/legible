from copy import deepcopy
import json

import pytest

from legible.analyze.analyzer import analyze_surface
from legible.analyze.classification import classify_surface
from legible.discover.surfaces import discover_surfaces
from legible.fetch.models import FetchObservation

HOME = 'http://127.0.0.1/'
REST = 'REST API reference. GET /widgets. '
AUTH = 'API requests authenticate using API keys in the X-API-Key header. '
ISSUE = 'Create an API key in the developer dashboard. '


def observation(url, text, status=200, media='text/html', error=None):
    return FetchObservation(url, url, status, media, text, error)


def check(text=REST, responses=None):
    responses = responses or {}
    discovery = discover_surfaces(observation(HOME, text), lambda url: responses.get(
        url, observation(url, 'Missing', 404, error='HTTP error: 404')))
    before = deepcopy(discovery)
    findings = analyze_surface(discovery, classify_surface(discovery))
    assert findings == analyze_surface(discovery, classify_surface(discovery))
    assert discovery == before
    assert all(f.evidence for f in findings)
    return {f.id: f for f in findings}


@pytest.mark.parametrize('text,auth,issuance', [
    (REST + AUTH + ISSUE, 'pass', 'pass'),
    (REST + AUTH, 'pass', 'fail'),
    (REST, 'fail', 'unknown'),
    (REST + 'The API requires no authentication.', 'not_applicable', 'not_applicable'),
    ('A bakery.', 'not_applicable', 'not_applicable'),
    ('Developer documentation coming soon.', 'unknown', 'unknown'),
    (REST + AUTH + 'Get a bearer token from the console.', 'pass', 'fail'),
    (REST + 'The API might use OAuth in the future.', 'unknown', 'unknown'),
    (REST + '<script>API requests use bearer tokens.</script>', 'fail', 'unknown'),
    (REST + 'Login Signup API key OAuth', 'unknown', 'unknown'),
    (REST + AUTH + 'The API requires no authentication.', 'unknown', 'unknown'),
])
def test_auth_states(text, auth, issuance):
    result = check(text)
    assert result['auth-mechanism'].state == auth
    assert result['key-issuance'].state == issuance


@pytest.mark.parametrize('text', [
    'API requests use bearer tokens in the Authorization header.',
    'API authentication uses OAuth 2.0.',
    'Authenticate API requests using signed requests.',
    'API requests use HTTP Basic authentication.',
])
def test_explicit_mechanisms(text):
    assert check(REST + text)['auth-mechanism'].state == 'pass'


@pytest.mark.parametrize('body,status,error', [
    ('Access denied', 200, None), ('Sign in', 200, None),
    ('API authentication', 403, 'HTTP error: 403'), ('', 200, None),
    ('API requests use API keys.', 500, 'HTTP error: 500'),
])
def test_unavailable_auth_docs_are_unknown(body, status, error):
    url = HOME + 'auth'
    result = check(REST + '<a href="/auth">Authentication</a>', {
        url: observation(url, body, status, error=error)})
    assert result['auth-mechanism'].state == 'unknown'
    assert result['key-issuance'].state == 'unknown'
    assert any(e.source_url == url for e in result['auth-mechanism'].evidence)


@pytest.mark.parametrize('media,body', [
    ('application/json', json.dumps({'openapi': '3.1.0', 'info': {}, 'paths': {}})),
    ('application/json', json.dumps({'swagger': '2.0', 'info': {}, 'paths': {}})),
    ('application/yaml', 'openapi: 3.0.3\ninfo:\n  title: Widgets\npaths: {}\n'),
])
def test_spec_pass(media, body):
    url = HOME + 'openapi.json'
    result = check(REST, {url: observation(url, body, media=media)})
    assert result['openapi'].state == 'pass'
    assert any('paths' in e.excerpt for e in result['openapi'].evidence)


@pytest.mark.parametrize('body,status,error', [
    ('{"openapi":"3.0.0"}', 200, None),
    ('<p>Swagger OpenAPI</p>', 200, None),
    ('openapi: 3.0.0\ninfo: nope\npaths: nope', 200, None),
    ('', 200, None), ('', 403, 'blocked'), ('', None, 'offline'),
])
def test_spec_ambiguous_is_unknown(body, status, error):
    url = HOME + 'openapi.json'
    assert check(REST, {url: observation(url, body, status, error=error)})['openapi'].state == 'unknown'


def test_spec_applicability_and_absence():
    assert check()['openapi'].state == 'fail'
    assert check('MCP server: connect your client.')['openapi'].state == 'not_applicable'
    assert check('Developer docs soon.')['openapi'].state == 'unknown'


def test_positive_auth_survives_failed_docs_but_issuance_is_unknown():
    url = HOME + 'auth'
    result = check(REST + AUTH + '<a href="/auth">Authentication</a>', {
        url: observation(url, '', 503, error='unavailable')})
    assert result['auth-mechanism'].state == 'pass'
    assert result['key-issuance'].state == 'unknown'


def test_checks_do_not_call_fetch_layer(monkeypatch):
    from legible.fetch import page
    def forbidden(*args, **kwargs):
        pytest.fail('Analysis must not fetch')
    monkeypatch.setattr(page, 'fetch_page', forbidden)
    monkeypatch.setattr(page, 'urlopen', forbidden)
    assert check(REST + AUTH + ISSUE)['key-issuance'].state == 'pass'


def test_spec_absence_retains_rest_applicability_evidence():
    result = check()['openapi']
    assert any('REST API' in e.excerpt for e in result.evidence)
    assert any(e.status == 404 for e in result.evidence)


def test_invalid_spec_version_pair_is_not_recognized():
    url = HOME + 'openapi.json'
    result = check(REST, {url: observation(url, '{"swagger":"3.1.0","info":{},"paths":{}}', media='application/json')})
    assert result['openapi'].state == 'unknown'
