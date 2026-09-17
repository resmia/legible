"""Controlled publisher patterns, using only synthetic public-surface fixtures."""
import json

import pytest

from legible import core
from legible.analyze.analyzer import analyze_surface
from legible.analyze.classification import classify_surface
from legible.discover.surfaces import MAX_FETCHES, discover_surfaces
from legible.fetch.models import FetchObservation
from legible.fix.fixer import create_fixes

HOME = 'https://example.com/'
AUTH = 'The API uses API keys for authentication. Authentication uses HTTP Basic Auth. '
ISSUE = 'Find your API keys in the developer dashboard. '


def run(pages, home_error=None):
    calls = []
    def fetch(url):
        calls.append(url)
        if url == HOME and home_error:
            return FetchObservation(url, status=home_error[0], error=home_error[1])
        if url in pages:
            return FetchObservation(url, url, 200,
                                    'text/plain' if url.endswith('.txt') else 'text/html', pages[url])
        return FetchObservation(url, url, 404, 'text/plain', 'Missing', 'HTTP error: 404')
    discovery = discover_surfaces(fetch(HOME), fetch)
    classification = classify_surface(discovery)
    findings = analyze_surface(discovery, classification)
    return discovery, classification, {f.id: f for f in findings}, calls


@pytest.mark.parametrize('pages,kind,auth,issuance,followed', [
    ({HOME: '<a href="/api/reference">API reference</a>',
      HOME+'api/reference': 'API reference. '+AUTH+ISSUE}, 'rest', 'pass', 'pass', HOME+'api/reference'),
    ({HOME: 'Welcome', 'https://docs.example.com/': 'Read /llms.txt for documentation.',
      'https://docs.example.com/llms.txt': '[Authentication](/auth)',
      'https://docs.example.com/auth': 'API reference. '+AUTH+ISSUE},
     'rest', 'pass', 'pass', 'https://docs.example.com/auth'),
    ({HOME: 'API reference. '+AUTH+ISSUE+'<a href="/mcp">MCP setup</a>',
      HOME+'mcp': 'MCP server: configure your client connection.'}, 'mixed', 'pass', 'pass', HOME+'mcp'),
    ({HOME: '<a href="/docs">Docs</a>', HOME+'docs': 'Read /docs/llms.txt for documentation.',
      HOME+'docs/llms.txt': '[MCP setup](/mcp)',
      HOME+'mcp': 'MCP server: connect using your client.'}, 'mcp', 'unknown', 'unknown', HOME+'mcp'),
    ({HOME: '<a href="/docs">Docs</a>',
      HOME+'docs': 'API reference. '+AUTH+'<a href="/docs/api/auth">Credentials</a>',
      HOME+'docs/api/auth': ISSUE}, 'rest', 'pass', 'pass', HOME+'docs/api/auth'),
])
def test_controlled_publisher_patterns(pages, kind, auth, issuance, followed):
    discovery, classification, findings, calls = run(pages)
    assert classification.kind == kind
    assert findings['auth-mechanism'].state == auth
    assert findings['key-issuance'].state == issuance
    assert followed in calls
    assert len(calls) == len(set(calls)) < MAX_FETCHES
    if kind == 'mcp':
        assert findings['openapi'].state == 'not_applicable'
    assert {f.id for f in findings.values()} == {'openapi', 'auth-mechanism', 'key-issuance'}


@pytest.mark.parametrize('error', [(403, 'HTTP error: 403'), (None, 'DNS lookup failed')])
def test_blocked_homepage_continues_and_preserves_uncertainty(error):
    discovery, classification, findings, calls = run({
        'https://docs.example.com/': 'API reference. '+AUTH,
    }, error)
    assert classification.kind == 'rest'
    assert findings['auth-mechanism'].state == 'pass'
    assert findings['key-issuance'].state == 'unknown'
    assert findings['openapi'].state == 'unknown'
    assert discovery.observations[0].error == error[1]
    assert 1 < len(calls) <= MAX_FETCHES


def test_pointers_preempt_guesses_and_low_value_links():
    pages = {HOME: '<a href="/docs">Docs</a>', HOME+'docs':
             ''.join(f'<a href="/docs/product-{i}">Docs product</a>' for i in range(50))+
             '<a href="/docs/api/auth">Credentials</a><a href="/docs/llms.txt">Index</a>',
             HOME+'docs/llms.txt': '[API reference](/reference)',
             HOME+'docs/api/auth': 'API reference. '+AUTH+ISSUE}
    discovery, _, findings, calls = run(pages)
    assert calls[:4] == [HOME, HOME+'docs', HOME+'docs/llms.txt', HOME+'reference']
    assert calls.index(HOME+'docs/api/auth') < calls.index('https://docs.example.com/')
    assert calls.index(HOME+'docs/api/auth') < calls.index(HOME+'docs/product-0')
    assert len(calls) == MAX_FETCHES
    assert discovery.pending_urls
    assert findings['key-issuance'].state == 'pass'
    assert run(pages)[3] == calls


def test_unknown_is_not_a_defect_and_explains_examined_evidence(tmp_path, monkeypatch):
    pages = {HOME: 'API reference. The API might use OAuth in the future.'}
    discovery, classification, findings, _ = run(pages)
    finding = findings['auth-mechanism']
    assert finding.state == 'unknown'
    assert 'examined' in finding.title and 'inconclusive' in finding.title
    assert finding.fix is None
    assert create_fixes([finding]) == []
    by_url = {o.requested_url: o for o in discovery.observations}
    monkeypatch.setattr(core, 'fetch_page', by_url.__getitem__)
    path = core.scan(HOME, str(tmp_path))
    markdown = (path/'report.md').read_text()
    assert 'HTTP error: 404; HTTP error: 404' not in markdown
    assert json.loads((path/'report.json').read_text())['discovery']['max_fetches'] == 30


def test_index_followups_do_not_expand_terminal_auth_pages():
    _, _, findings, calls = run({HOME: '<a href="/docs">Docs</a>',
        HOME+'docs': '<a href="/docs/llms.txt">Index</a>',
        HOME+'docs/llms.txt': '[Credentials](/auth)',
        HOME+'auth': 'API reference. '+AUTH+ISSUE+'<a href="/auth/deeper">Authentication</a>'})
    assert findings['key-issuance'].state == 'pass'
    assert HOME+'auth/deeper' not in calls


def test_scan_stops_guessing_when_published_evidence_settles_checks(tmp_path, monkeypatch):
    pages = {HOME: 'API reference. '+AUTH+ISSUE+'<a href="/openapi.json">OpenAPI</a>',
             HOME+'openapi.json': '{"openapi":"3.1.0","info":{},"paths":{}}'}
    calls = []
    def fetch(url):
        calls.append(url)
        return FetchObservation(url, url, 200, 'text/html', pages[url])
    monkeypatch.setattr(core, 'fetch_page', fetch)
    path = core.scan(HOME, str(tmp_path))
    report = json.loads((path/'report.json').read_text())
    assert calls == [HOME, HOME+'openapi.json']
    assert all(f['state'] == 'pass' for f in report['findings'])
    assert report['discovery']['pending_urls']


def test_unavailable_and_inconclusive_unknown_have_different_explanations():
    _, _, findings, _ = run({HOME: 'API reference. <a href="/auth">Authentication</a>'})
    assert findings['auth-mechanism'].state == 'unknown'
    assert 'unavailable or blocked' in findings['auth-mechanism'].title
    assert findings['auth-mechanism'].fix is None


def test_incidental_api_mention_does_not_establish_rest():
    _, classification, _, _ = run({HOME: 'Our product connects to an API for analytics.'})
    assert classification.kind in {'none', 'unknown'}
