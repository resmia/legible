"""Synthetic end-to-end evidence scheduling and specification regressions."""
import json

import pytest

from legible import core
from legible.fetch.models import FetchObservation

HOME = 'https://example.com/'
SPEC = 'openapi: 3.1.0\ninfo:\n  title: Widgets\npaths: {}\n'
BEHAVIOR = 'Error response: {"error": {"code": "invalid_request"}}. Retry transient failures with exponential backoff. '
AUTH = BEHAVIOR + 'API requests authenticate using API keys in the X-API-Key header. '
ISSUE = 'Create an API key in the developer dashboard. '


def scan(monkeypatch, tmp_path, pages, failed_hosts=False):
    calls = []

    def fetch(url):
        calls.append(url)
        if url in pages:
            body, media = pages[url]
            return FetchObservation(url, url, 200, media, body)
        if failed_hosts and url != HOME and url.endswith('/'):
            return FetchObservation(url, error='DNS lookup failed')
        return FetchObservation(url, url, 404, 'text/plain', 'Missing', 'HTTP error: 404')

    monkeypatch.setattr(core, 'fetch_page', fetch)
    output = core.scan(HOME, str(tmp_path))
    report = json.loads((output / 'report.json').read_text())
    assert len(calls) <= 30 and len(calls) == len(set(calls))
    assert len(report['observations']) == len(calls)
    for surface in report['discovery']['surfaces']:
        assert report['observations'][surface['observation_index']]['requested_url'] == surface['url']
    return calls, report, (output / 'report.md').read_text()


def html(body):
    return body, 'text/html'


@pytest.mark.parametrize('body,passes', [
    (SPEC, True),
    ('{"openapi":"3.0.3","info":{},"paths":{}}', True),
    ('---\n"openapi": "3.1.0" # version\ninfo: {title: Widgets}\npaths:\n  /widgets:\n    get: {}\n', True),
    ('openapi: 3.1.0\ninfo:\n  description: |\n    <p>API docs</p>\npaths: {}', True),
    ('openapi: 3.1.0\ninfo: {}\npaths: {}\nbroken: [', False),
    ('openapi: 3.1.0\ninfo: []\npaths: {}', False),
    ('openapi: 3.1.0\ninfo: {}\npaths: null', False),
    ('title: Generic YAML\ninfo: {}\npaths: {}', False),
    ('example: |\n  openapi: 3.1.0\n  info: {}\n  paths: {}', False),
    ('openapi: 3.1.0\ninfo: {}\npaths: {}\n---\ntitle: Second document', False),
    ('swagger: 3.1.0\ninfo: {}\npaths: {}', False),
])
def test_specification_structure(monkeypatch, tmp_path, body, passes):
    _, report, _ = scan(monkeypatch, tmp_path, {
        HOME: html('<a href="/openapi.yaml">OpenAPI</a>'),
        HOME+'openapi.yaml': (body, 'application/yaml'),
    })
    finding = next(f for f in report['findings'] if f['id'] == 'openapi')
    assert (finding['state'] == 'pass') == passes
    if passes:
        assert report['classification']['kind'] == 'rest'


def test_stops_lower_priority_expansion_but_preserves_indexes_and_mixed(monkeypatch, tmp_path):
    calls, report, markdown = scan(monkeypatch, tmp_path, {
        HOME: html('API reference. '+AUTH+ISSUE+'<a href="/docs">Docs</a>'),
        HOME+'docs': html('Read /docs/llms.txt. '+''.join(
            f'<a href="/docs/resource-{i}">API resource</a>' for i in range(50))),
        HOME+'docs/llms.txt': ('[OpenAPI](/openapi.yaml)\n[MCP setup](/mcp)', 'text/plain'),
        HOME+'openapi.yaml': (SPEC, 'application/yaml'),
        HOME+'mcp': html('MCP server: configure your client connection to https://example.com/mcp.'),
    })
    assert len(calls) == 5
    assert report['classification']['kind'] == 'mixed'
    assert all(f['state'] in {'pass', 'not_applicable'} for f in report['findings'])
    assert report['discovery']['pending_urls']
    assert 'pass' in markdown


def test_relevance_and_dynamic_priority(monkeypatch, tmp_path):
    links = (
        '<a href="/user-authentication">User authentication MFA marketing</a>'
        '<a href="/general-auth">Authentication</a>'
        '<a href="/api-auth">API request authentication</a>'
        '<a href="/credentials">Developer credentials</a>'
        '<a href="/api-auth-extra">API request authentication details</a>'
    )
    calls, report, _ = scan(monkeypatch, tmp_path, {
        HOME: html('<a href="/docs">Docs</a>'),
        HOME+'docs': html('API reference. '+links.replace('</a>', '</a>. ')+'<a href="/openapi.yaml">OpenAPI</a>'),
        HOME+'openapi.yaml': (SPEC, 'application/yaml'),
        HOME+'credentials': html(ISSUE),
        HOME+'llms.txt': ('[API reference](/docs)', 'text/plain'),
        HOME+'api-auth': html(AUTH),
    })
    assert calls.index(HOME+'credentials') < calls.index(HOME+'api-auth')
    assert HOME+'general-auth' not in calls
    assert HOME+'user-authentication' not in calls
    assert HOME+'api-auth-extra' not in calls
    assert all(f['state'] in {'pass', 'not_applicable'} for f in report['findings'])


def test_unresolved_relevant_evidence_can_exhaust_budget(monkeypatch, tmp_path):
    pages = {HOME: html('API reference. '+AUTH+'<a href="/docs">Docs</a>'),
             HOME+'docs': html(''.join(
                 f'<a href="/credentials-{i}">Create API keys</a>' for i in range(50)))}
    pages.update({HOME+f'credentials-{i}': html('Developer credentials instructions coming soon.')
                  for i in range(50)})
    calls, report, _ = scan(monkeypatch, tmp_path, pages)
    assert len(calls) == 30
    assert report['discovery']['pending_urls']
    assert next(f for f in report['findings'] if f['id'] == 'key-issuance')['state'] == 'unknown'


def test_speculative_failures_do_not_claim_documented_sources_blocked(monkeypatch, tmp_path):
    _, report, _ = scan(monkeypatch, tmp_path, {
        HOME: html('<a href="/docs">Docs</a>'),
        HOME+'docs': html('API reference. Authentication details might use OAuth.'),
    }, failed_hosts=True)
    auth = next(f for f in report['findings'] if f['id'] == 'auth-mechanism')
    assert auth['state'] == 'unknown'
    assert 'examined' in auth['title'] and 'inconclusive' in auth['title']
    assert 'unavailable or blocked' not in auth['title']
    assert any(o['error'] == 'DNS lookup failed' for o in report['observations'])
    assert auth['fix'] is None


@pytest.mark.parametrize('label', [
    'User authentication', 'Identity verification', 'MFA authentication',
    'Customer login security', 'Fraud authentication ebook', 'Consumer onboarding',
])
def test_consumer_links_do_not_outrank_api_auth(monkeypatch, tmp_path, label):
    calls, report, _ = scan(monkeypatch, tmp_path, {
        HOME: html('API reference. '+ISSUE+'<a href="/docs/marketing">'+label+'</a>. '
                   '<a href="/api-auth">API request authentication</a>. '
                   '<a href="/openapi.yaml">OpenAPI</a>'),
        HOME+'openapi.yaml': (SPEC, 'application/yaml'),
        HOME+'llms.txt': ('[API reference](/docs)', 'text/plain'),
        HOME+'api-auth': html(AUTH),
    })
    assert HOME+'api-auth' in calls
    assert HOME+'docs/marketing' not in calls
    assert all(f['state'] in {'pass', 'not_applicable'} for f in report['findings'])


def test_documented_host_failure_remains_unavailable(monkeypatch, tmp_path):
    _, report, _ = scan(monkeypatch, tmp_path, {
        HOME: html('API reference. <a href="https://api.example.com/">Authentication</a>'),
    }, failed_hosts=True)
    auth = next(f for f in report['findings'] if f['id'] == 'auth-mechanism')
    assert auth['state'] == 'unknown'
    assert 'unavailable or blocked' in auth['title']
    surface = next(s for s in report['discovery']['surfaces'] if s['url'] == 'https://api.example.com/')
    assert surface['reason'] == 'published_link'


def test_pending_auth_pointer_is_followed_when_other_checks_pass(monkeypatch, tmp_path):
    calls, report, _ = scan(monkeypatch, tmp_path, {
        HOME: html('API reference. '+ISSUE+'<a href="/docs">Docs</a>'),
        HOME+'docs': html('<a href="/openapi.yaml">OpenAPI</a>. '
                         '<a href="/docs/llms.txt">Index</a>'),
        HOME+'docs/llms.txt': ('[Request authentication](/api-auth)', 'text/plain'),
        HOME+'openapi.yaml': (SPEC, 'application/yaml'),
        HOME+'llms.txt': ('[API reference](/docs)', 'text/plain'),
        HOME+'api-auth': html(AUTH),
    })
    assert HOME+'api-auth' in calls
    assert all(f['state'] in {'pass', 'not_applicable'} for f in report['findings'])
