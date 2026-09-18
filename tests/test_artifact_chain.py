"""A delegated specification repository is a bounded trail, not a crawl root."""
import socket
import pytest
from legible.fetch import safety
from test_discovery_correctness import run, HOME, SPEC

REPO = 'https://source.other.test/team/contract'
DIRECTORY = REPO + '/tree/main/latest'
FILE = REPO + '/blob/main/latest/api.yaml'
RAW = 'https://content.other.test/team/contract/main/latest/api.yaml'


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))])


def pages():
    return {HOME: (f'<a href="{REPO}">Official OpenAPI repository</a>', 'text/html'),
        REPO: (f'<a href="/other/repo/spec.yaml">OpenAPI</a><a href="{REPO}/issues">Issues</a><a href="{REPO}/package.json">package.json</a><a href="{DIRECTORY}">latest</a>', 'text/html'),
        DIRECTORY: (f'<a href="{FILE}">api.yaml</a>', 'text/html'),
        FILE: (f'<a href="{RAW}">Raw</a><a href="https://unrelated.test/spec.yaml">Other specification</a>', 'text/html'),
        RAW: (SPEC, 'application/yaml')}


def test_full_chain_and_provenance(monkeypatch):
    report, calls = run(monkeypatch, pages())
    assert all(url in calls for url in [REPO, DIRECTORY, FILE, RAW])
    assert not any('/other/repo' in u or '/issues' in u or '/package.json' in u or 'unrelated.test' in u for u in calls)
    assert next(f for f in report.findings if f.id == 'openapi').state == 'pass'
    for source, target in zip([HOME, REPO, DIRECTORY, FILE], [REPO, DIRECTORY, FILE, RAW]):
        assert next(s for s in report.discovery.surfaces if s.url == target).source_url == source


def test_fake_spec_is_not_positive(monkeypatch):
    data = pages(); data[RAW] = ('Just some prose. [OpenAPI](https://more.other.test/spec.yaml)', 'text/plain')
    report, calls = run(monkeypatch, data)
    assert next(f for f in report.findings if f.id == 'openapi').state != 'pass'
    assert 'https://more.other.test/spec.yaml' not in calls


def test_only_one_bounded_chain(monkeypatch):
    data = pages()
    second = 'https://second.other.test/team/openapi'
    data[HOME] = (data[HOME][0] + f'<a href="{second}">OpenAPI repository</a>', 'text/html')
    data[second] = ('<a href="/team/openapi/spec.yaml">OpenAPI</a>', 'text/html')
    report, calls = run(monkeypatch, data)
    assert sum(u in calls for u in [DIRECTORY, FILE, RAW]) == 3
    assert second + '/spec.yaml' not in calls
    assert len(calls) <= 30


def test_external_raw_link_only_from_selected_file(monkeypatch):
    data = pages(); data[REPO] = (f'<a href="{RAW}">Raw OpenAPI</a>', 'text/html')
    _, calls = run(monkeypatch, data)
    assert RAW not in calls


def test_chain_depth_stops(monkeypatch):
    data = pages()
    for depth in range(5):
        url = REPO + '/spec' * (depth + 1)
        parent = REPO if depth == 0 else REPO + '/spec' * depth
        data[parent] = (f'<a href="{url}">specification directory</a>', 'text/html')
    _, calls = run(monkeypatch, data)
    assert REPO + '/spec' * 3 in calls
    assert REPO + '/spec' * 4 not in calls


def test_published_changelog_text_precedes_old_release_navigation(monkeypatch):
    data = pages()
    data[HOME] = ('<a href="/changelog">API changelog</a><a href="/docs">Docs</a>', 'text/html')
    data[HOME+'changelog'] = (''.join(f'<a href="/changelog/release-{i}">API changes</a>' for i in range(50)), 'text/html')
    data[HOME+'docs'] = ('<a href="/docs/llms.txt">llms.txt</a>', 'text/html')
    data[HOME+'docs/llms.txt'] = ('[Changelog](/changelog.md)', 'text/plain')
    data[HOME+'changelog.md'] = ('[OpenAPI release](/releases/spec.md)', 'text/markdown')
    data[HOME+'releases/spec.md'] = (f'[OpenAPI repository]({REPO})', 'text/markdown')
    report, calls = run(monkeypatch, data)
    assert RAW in calls
    assert next(f for f in report.findings if f.id == 'openapi').state == 'pass'


def test_malicious_spec_destination_cannot_be_positive(monkeypatch):
    data = pages()
    data[FILE] = ('<a href="https://127.0.0.1/spec.yaml">Raw</a>', 'text/html')
    # Mixed/public DNS fixtures must not stand in for a literal private answer.
    resolve = safety.socket.getaddrinfo
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda host, port, **kw:
        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))] if host == '127.0.0.1' else resolve(host, port, **kw))
    report, calls = run(monkeypatch, data)
    assert 'https://127.0.0.1/spec.yaml' not in calls
    assert next(f for f in report.findings if f.id == 'openapi').state != 'pass'


def test_sibling_contract_resolves_checks_without_becoming_openapi(monkeypatch):
    contract = 'https://platform.widget.test/llms.txt'
    data = {HOME: ('Read /llms.txt', 'text/html'),
        HOME+'llms.txt': (f'Canonical machine-readable API contract: {contract}', 'text/plain'),
        contract: ('API base URL: https://api.widget.test/v1. '
            'Authenticate requests with an API key supplied as a bearer token in the Authorization header. '
            'Create an API key in the dashboard. Self-hosted CLI: run widget init. '
            'Error response: {"error":{"code":"invalid_input","message":"Bad input","details":[]}}. '
            'HTTP 500 is retryable with exponential backoff. HTTP 400 is non-retryable; fix the request. '
            'Retry with the same idempotency key to avoid duplicate operations.', 'text/plain')}
    report, calls = run(monkeypatch, data)
    outcomes = {f.id: f.state for f in report.findings}
    assert contract in calls
    assert outcomes == {'openapi':'unknown', 'auth-mechanism':'pass', 'key-issuance':'pass',
        'llms-txt':'pass', 'typed-errors':'pass', 'retry-guidance':'pass', 'mcp-discovery':'not_applicable'}
    assert 'REST applicability is unresolved' not in report.findings[0].title


def test_related_origin_provenance_survives_later_candidates(monkeypatch):
    docs = 'https://platform.widget.test/docs'
    contract = 'https://platform.widget.test/llms.txt'
    report, _ = run(monkeypatch, {HOME: (f'<a href="{docs}">Docs</a>', 'text/html'),
        docs: (f'[Canonical API contract]({contract})', 'text/plain'), contract: ('API reference', 'text/plain')})
    surface = next(s for s in report.discovery.surfaces if s.url == contract)
    assert surface.source_url == docs and 'related-origin' in surface.link_text


def test_malformed_repository_links_are_ignored(monkeypatch):
    data = pages()
    data[REPO] = ('<a href="https://[broken/spec.yaml">OpenAPI</a>' + data[REPO][0], 'text/html')
    report, calls = run(monkeypatch, data)
    assert RAW in calls
    assert next(f for f in report.findings if f.id == 'openapi').state == 'pass'
