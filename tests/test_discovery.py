import json

import pytest

from legible import core
from legible.discover.surfaces import (
    MAX_FETCHES, MAX_LINKS, PUBLIC_FILES, discover_surfaces, initial_candidates,
)
from legible.fetch.models import FetchObservation


HOME = 'https://example.com/'


def html(url, text='', final=None):
    return FetchObservation(url, final or url, 200, 'text/html; charset=utf-8', text)


def discover(homepage, responses=None):
    calls = []
    responses = responses or {}

    def fetch(url):
        calls.append(url)
        return responses.get(url, FetchObservation(url, error='offline'))

    return discover_surfaces(homepage, fetch), calls


def test_fixed_candidates_and_failed_probe_evidence():
    result, calls = discover(html(HOME))
    assert calls == [
        *[HOME.rstrip('/') + path for path in PUBLIC_FILES],
        'https://docs.example.com/', 'https://api.example.com/',
        'https://developer.example.com/', 'https://developers.example.com/',
    ]
    assert len(result.observations) == 11
    assert all(item.error == 'offline' for item in result.observations[1:])
    assert [s.observation_index for s in result.surfaces] == list(range(11))


@pytest.mark.parametrize('homepage', ['http://127.0.0.1:8123/', 'http://[::1]:8123/', 'http://localhost:8123/'])
def test_local_hosts_only_probe_files(homepage):
    candidates = initial_candidates(homepage)
    assert len(candidates) == 7
    assert [url for url, _ in candidates[1:]] == [homepage.rstrip('/') + p for p in PUBLIC_FILES]


def test_www_host_guesses_preserve_scheme_port():
    candidates = initial_candidates('http://www.example.com:8080/')
    assert candidates[1] == ('http://docs.example.com:8080/', 'likely_host')


def test_links_use_redirect_base_deduplicate_and_do_not_recurse():
    home = html(HOME, '''
        <a href="auth#keys">Authentication</a>
        <a href="auth#other">Duplicate</a>
        <a href="https://docs.example.com/">Docs</a>
        <a href="/openapi.json">OpenAPI</a>
    ''', final='https://www.example.com/guide/')
    auth = 'https://www.example.com/guide/auth'
    docs = 'https://docs.example.com/'
    result, calls = discover(home, {
        auth: html(auth, '<a href="/errors/deeper">Errors</a>'),
        docs: html(docs, '<a href="/rate-limits">Rate limits</a>'),
    })
    assert calls.count(docs) == 1
    assert calls.count(auth) == 1
    assert 'https://docs.example.com/rate-limits' in calls
    assert not any('deeper' in url for url in calls)
    surface = next(s for s in result.surfaces if s.url == auth)
    assert surface.source_url == home.final_url
    assert surface.link_text == 'Authentication'
    assert surface.reason == 'published_link'


def test_deterministic_global_link_and_fetch_caps():
    home = html(HOME, ''.join(f'<a href="/api/{i}">API</a>' for i in range(50)))
    result, calls = discover(home)
    again, again_calls = discover(home)
    assert calls == again_calls
    assert result == again
    assert len(result.observations) == MAX_FETCHES == 30
    assert calls[10:] == [f'{HOME}api/{i}' for i in range(19)]


@pytest.mark.parametrize('link', [
    '<a href="#auth">Authentication</a>',
    '<a href="javascript:alert(1)">API</a>',
    '<a href="mailto:api@example.com">API</a>',
    '<a href="https://user:secret@example.com/auth">Auth</a>',
    '<a href="/auth?token=secret">Auth</a>',
    '<a href="https://external.example.org/docs">Docs</a>',
    '<a href="https://example.com.evil.test/docs">Docs</a>',
    '<a href="https://new.example.com/docs">Docs</a>',
    '<a href="http://[broken/auth">Auth</a>',
    '<a href="/capital">Capital</a>',
    '<a href="/products">Products</a>',
    '<a href="/login">Sign in</a>',
])
def test_link_rejection_and_keyword_false_positives(link):
    result, calls = discover(html(HOME, link))
    assert len(calls) == 10
    assert len(result.observations) == 11


@pytest.mark.parametrize('content_type,status,error', [
    ('text/plain', 200, None), ('application/json', 200, None),
    ('text/html', 404, 'HTTP error: 404'), ('text/html', 500, None),
    (None, 200, None),
])
def test_only_successful_html_seeds_supply_links(content_type, status, error):
    docs = 'https://docs.example.com/'
    result, calls = discover(html(HOME), {
        docs: FetchObservation(docs, docs, status, content_type,
                               '<a href="/auth">Auth</a>', error),
    })
    assert len(calls) == 10


def test_scan_serializes_all_evidence_and_provenance(tmp_path, monkeypatch):
    def fetch(url):
        if url == HOME:
            return html(url, '<a href="/authentication">Authentication</a>')
        if url.endswith('/.well-known/mcp-server-card'):
            return FetchObservation(url, url, 200, 'application/json', '{"name":"fixture"}')
        return FetchObservation(url, url, 404, 'text/plain', 'Missing', 'HTTP error: 404')

    monkeypatch.setattr(core, 'fetch_page', fetch)
    path = core.scan(HOME, str(tmp_path))
    report = json.loads((path / 'report.json').read_text())
    assert len(report['findings']) == 3
    assert len(report['observations']) == 12
    for surface in report['discovery']['surfaces']:
        assert report['observations'][surface['observation_index']]['requested_url'] == surface['url']
    linked = next(s for s in report['discovery']['surfaces'] if s['reason'] == 'published_link')
    assert linked['source_url'] == HOME
    assert linked['reason'] == 'published_link'
    markdown = (path / 'report.md').read_text()
    assert 'Linked from: https://example.com/' in markdown
    assert 'Fetch error: HTTP error: 404' in markdown
    assert 'Assessed openapi' in markdown
