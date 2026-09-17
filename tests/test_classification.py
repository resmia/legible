from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from legible import core
from legible.analyze.classification import classify_surface
from legible.discover.surfaces import discover_surfaces, DiscoveryResult
from legible.fetch.models import FetchObservation

HOME = 'https://example.com/'


def observation(url=HOME, text='<p>A neighborhood bakery. Bread baked daily.</p>', **kwargs):
    return FetchObservation(url, kwargs.get('final', url), kwargs.get('status', 200),
                            kwargs.get('media', 'text/html'), text, kwargs.get('error'))


def discovery(text, responses=None):
    responses = responses or {}
    return discover_surfaces(observation(text=text), lambda url: responses.get(
        url, observation(url, 'Missing', status=404, error='HTTP error: 404')))


@pytest.mark.parametrize('text,kind', [
    ('<h1>REST API reference</h1><pre>GET /v1/widgets</pre>', 'rest'),
    ('<h1>MCP server</h1><p>Connect using your client configuration.</p>', 'mcp'),
    ('REST API reference: GET /widgets. MCP server: connect your client.', 'mixed'),
    ('<h1>Python SDK</h1><pre>pip install example-sdk</pre>', 'sdk'),
    ('<h1>Command-line interface</h1><pre>brew install example</pre>', 'cli'),
    ('Developer documentation is coming soon.', 'unknown'),
    ('A neighborhood bakery. Bread baked daily.', 'none'),
])
def test_documentation_classification(text, kind):
    result = discovery(text)
    before = deepcopy(result)
    classification = classify_surface(result)
    assert classification.kind == kind
    assert classification == classify_surface(result)
    assert result == before
    assert classification.evidence


def test_openapi_json_with_redirect_provenance():
    url = HOME + 'openapi.json'
    result = discovery('Welcome', {url: observation(
        url, json.dumps({'openapi': '3.1.0', 'info': {'title': 'Example'}, 'paths': {}}),
        media='application/json', final=HOME + 'spec.json')})
    classification = classify_surface(result)
    assert classification.kind == 'rest'
    evidence, = [e for e in classification.evidence if e.signal == 'api-spec-document']
    assert evidence.source_url == HOME + 'spec.json'
    assert result.observations[evidence.observation_index].requested_url == url


@pytest.mark.parametrize('text', [
    'Our editorial covers API and CLI trends.',
    'REST API is planned. GET /example is an illustration.',
    'No MCP server is available; do not connect.',
    'SDK roadmap: pip install example is not supported.',
    '<script>REST API GET /widgets</script><p>Welcome</p>',
    '<style>/* MCP server connect */</style><p>Welcome</p>',
    '<a href="/cli">CLI</a>',
    'The capital city has a pleasant climate.',
])
def test_no_positive_classification_from_incidental_or_negative_text(text):
    assert classify_surface(discovery(text)).kind in {'none', 'unknown'}


@pytest.mark.parametrize('response', [
    observation(HOME + 'openapi.json', 'REST API GET /widgets', status=500, error='HTTP error: 500'),
    observation(HOME + 'openapi.json', '', status=200),
    observation(HOME + 'openapi.json', 'REST API GET /widgets', media='image/png'),
    FetchObservation(HOME + 'openapi.json', error='offline'),
])
def test_unresolved_probe_prevents_none(response):
    assert classify_surface(discovery('A bakery.', {response.requested_url: response})).kind == 'unknown'


@pytest.mark.parametrize('text', ['', '<html><script>app()</script></html>'])
def test_unreadable_homepage_is_unknown(text):
    assert classify_surface(discovery(text)).kind == 'unknown'


def test_missing_coverage_is_unknown():
    assert classify_surface(DiscoveryResult()).kind == 'unknown'
    assert classify_surface(DiscoveryResult(observations=[observation()])).kind == 'unknown'


def test_published_developer_link_prevents_none_even_when_missing():
    result = discovery('<p>A bakery.</p><a href="/docs">Read more</a>')
    assert classify_surface(result).kind == 'unknown'


def test_candidate_url_and_unrecognized_json_are_not_positive_evidence():
    url = HOME + '.well-known/mcp-server-card'
    result = discovery('Welcome', {url: observation(url, '{"name":"example"}', media='application/json')})
    assert classify_surface(result).detected_types == []


def test_scan_reports_classification_without_changing_observations(tmp_path, monkeypatch):
    result = discovery('REST API reference: GET /widgets. MCP server: connect your client.')
    by_url = {o.requested_url: o for o in result.observations}
    calls = []
    def fetch(url):
        calls.append(url)
        return by_url[url]
    monkeypatch.setattr(core, 'fetch_page', fetch)
    path = core.scan(HOME, str(tmp_path))
    report = json.loads((path / 'report.json').read_text())
    assert calls == list(by_url)
    assert report['observations'] == [asdict(o) for o in result.observations]
    assert report['discovery']['surfaces'] == [asdict(s) for s in result.surfaces]
    assert report['classification'] == asdict(classify_surface(result))
    assert report['classification']['detected_types'] == ['mcp', 'rest']
    assert len(report['findings']) == 3
    markdown = (path / 'report.md').read_text()
    assert 'Surface: mixed' in markdown
    assert 'Observation 0: https://example.com/' in markdown
    assert 'rest-documentation' in markdown and 'mcp-documentation' in markdown


def test_positive_evidence_survives_incomplete_coverage():
    result = discovery('REST API reference: GET /widgets', {
        HOME + 'openapi.json': FetchObservation(HOME + 'openapi.json', error='offline'),
    })
    classification = classify_surface(result)
    assert classification.kind == 'rest'
    assert any(e.signal == 'unresolved' for e in classification.evidence)


@pytest.mark.parametrize('media,text', [
    ('application/json', '{"name":"fixture"}'),
    ('application/yaml', 'title: Example\npaths: {}'),
])
def test_unrecognized_structured_artifacts_remain_unknown(media, text):
    url = HOME + 'openapi.json'
    result = discovery('A bakery.', {url: observation(url, text, media=media)})
    assert classify_surface(result).kind == 'unknown'
