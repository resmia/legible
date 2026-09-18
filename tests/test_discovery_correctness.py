"""Small fictional regressions for published integration trails."""
import pytest
from legible import core
from legible.fetch.models import FetchObservation
from legible.analyze.analyzer import analyze_surface
from legible.analyze.classification import classify_surface
from legible.discover.surfaces import DiscoveryResult, DiscoveredSurface

HOME = 'https://www.widget.test/'
SPEC = '{"openapi":"3.1.0","info":{},"paths":{}}'


def run(monkeypatch, pages):
    calls = []
    def fetch(url):
        calls.append(url)
        body, media = pages.get(url, ('Missing', 'text/plain'))
        status = 200 if url in pages else 404
        return FetchObservation(url, url, status, media, body, None if status == 200 else 'Missing')
    monkeypatch.setattr(core, 'fetch_page', fetch)
    report = core.scan_report(HOME)
    assert len(calls) <= 30
    return report, calls


def evaluate(text, media='text/plain', path='llms.txt'):
    url = HOME+path
    o = FetchObservation(url, url, 200, media, text)
    d = DiscoveryResult([o], [DiscoveredSurface(url, 'published_link', HOME, 'API documentation', 0)])
    c = classify_surface(d)
    return c, {f.id: f for f in analyze_surface(d, c)}


def test_description_rank_beats_large_navigation(monkeypatch):
    index = '\n'.join(f'[API tutorial {i}](/guide/{i})' for i in range(60))
    index += '\n[Gateway Errors](/gateway) - which responses are safe to retry\n[OpenAPI](/contract.json)'
    report, calls = run(monkeypatch, {HOME: ('API reference. Read /llms.txt', 'text/html'),
        HOME+'llms.txt': (index, 'text/plain'), HOME+'gateway': ('HTTP 500: retry with exponential backoff.', 'text/plain'),
        HOME+'contract.json': (SPEC, 'application/json')})
    assert calls.index(HOME+'gateway') < 6
    assert calls.index(HOME+'contract.json') < 6
    assert {f.id:f.state for f in report.findings}['retry-guidance'] == 'pass'
    assert calls == run(monkeypatch, {HOME: ('API reference. Read /llms.txt', 'text/html'),
        HOME+'llms.txt': (index, 'text/plain'), HOME+'gateway': ('HTTP 500: retry with exponential backoff.', 'text/plain'),
        HOME+'contract.json': (SPEC, 'application/json')})[1]


@pytest.mark.parametrize('text', [
 'Create credential stubs so MCP servers can start. Configure the server environment.',
 'The gateway injects credentials into MCP server environment variables. Configure credentials.',
 'Agents send MCP/plugin tool schemas with requests.',
 '<nav>Model Context Protocol</nav><p>API reference</p>',
 '<div>Repository topics: mcp</div>',
])
def test_consumer_mcp_is_not_provider(text):
    c, f = evaluate(text, 'text/html')
    assert 'mcp' not in c.detected_types
    assert f['mcp-discovery'].state == 'not_applicable'


def test_provider_mcp():
    c, f = evaluate('Our MCP server: connect to https://mcp.widget.test. Client configuration: {"mcpServers":{"widget":{"url":"https://mcp.widget.test"}}}')
    assert 'mcp' in c.detected_types
    assert f['mcp-discovery'].state == 'pass'


def test_concise_contract_entry_and_rest():
    c, f = evaluate('API base URL: https://api.widget.test/v1. Setup: create an API key in the dashboard. '
        'Authenticate requests using bearer tokens. Canonical machine-readable API contract: https://platform.widget.test/llms.txt. '
        'Self-hosted CLI: run widget init to configure the command line.')
    assert {'rest', 'cli'} <= set(c.detected_types)
    assert f['llms-txt'].state == 'pass'
    assert f['openapi'].state == 'unknown'
    assert 'REST applicability is unresolved' not in f['openapi'].title


@pytest.mark.parametrize('text', ['', 'Our product is amazing. Try it today.'])
def test_promotional_entry(text):
    assert evaluate(text)[1]['llms-txt'].state != 'pass'


@pytest.mark.parametrize('text', [
 'API reference. Errors Attributes status integer HTTP status. code nullable string Error code identifying the failure. '
 'type string Error category. message nullable string Explanation. param nullable string Related field.',
 'API reference. Error response: {"error":{"code":"invalid_input","message":"Wrong value","details":[]}}. invalid_input means HTTP 400.',
 'API reference. Error codes | status | meaning: invalid_input | 400 | fix the request; service_busy | 503 | retry later.',
])
def test_structured_error_models(text):
    assert evaluate(text)[1]['typed-errors'].state == 'pass'


@pytest.mark.parametrize('text', [
 'HTTP status | retryable | response: 500 | yes | exponential backoff.',
 '429/502/503/504 are retryable; 400/401/403/409 are non-retryable. Fix the request before retrying.',
 'On connection failure, retry with the same idempotency key to avoid duplicate operations.',
])
def test_retry_contracts(text):
    assert evaluate('API reference. '+text)[1]['retry-guidance'].state == 'pass'


def test_bare_error_retry_not_positive():
    _, f = evaluate('API reference. Errors may occur. Retry is a concept.')
    assert f['typed-errors'].state != 'pass' and f['retry-guidance'].state != 'pass'


@pytest.fixture
def public_dns(monkeypatch):
    import socket
    from legible.fetch import safety
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', port))])


def test_related_contract_and_api_location(monkeypatch, public_dns):
    platform = 'https://platform.widget.test/llms.txt'
    api = 'https://api.widget.test/'
    report, calls = run(monkeypatch, {HOME: ('Read /llms.txt', 'text/html'),
        HOME+'llms.txt': (f'Canonical machine-readable API contract: {platform}', 'text/plain'),
        platform: (f'API base URL: {api}\nAPI reference. Authenticate requests with bearer tokens.', 'text/plain')})
    assert platform in calls and api in calls
    s = next(s for s in report.discovery.surfaces if s.url == platform)
    assert s.source_url == HOME+'llms.txt' and 'related-origin' in s.link_text
    assert 'rest' in report.classification.detected_types


def test_published_external_spec_is_one_hop(monkeypatch, public_dns):
    external = 'https://artifacts.other.test/openapi.json'
    report, calls = run(monkeypatch, {HOME: (f'<a href="{external}">Official OpenAPI specification</a>', 'text/html'),
        external: (SPEC, 'application/json')})
    assert external in calls
    assert next(f for f in report.findings if f.id == 'openapi').state == 'pass'
    s = next(s for s in report.discovery.surfaces if s.url == external)
    assert s.source_url == HOME and 'one-hop' in s.link_text
    _, calls = run(monkeypatch, {HOME: (f'<a href="{external}">Official API documentation</a>', 'text/html'),
        external: ('<a href="https://elsewhere.test/openapi.json">OpenAPI</a><a href="/next">Docs</a>', 'text/html')})
    assert 'https://elsewhere.test/openapi.json' not in calls and 'https://artifacts.other.test/next' not in calls


def test_origin_caps_and_unrelated_links(monkeypatch, public_dns):
    from legible.discover.surfaces import MAX_RELATED_ORIGINS, MAX_EXTERNAL_ARTIFACTS
    links = ''.join(f'<a href="https://p{i}.widget.test/llms.txt">Canonical API documentation</a>' for i in range(8))
    links += ''.join(f'<a href="https://external{i}.other.test/spec.json">OpenAPI</a>' for i in range(8))
    links += '<a href="https://widget.test.evil.invalid/llms.txt">Docs</a><a href="https://shop.other.test/">Buy shoes</a>'
    _, calls = run(monkeypatch, {HOME:(links, 'text/html')})
    assert sum('https://p' in u for u in calls) == MAX_RELATED_ORIGINS
    assert sum('https://external' in u for u in calls) == MAX_EXTERNAL_ARTIFACTS
    assert not any('evil.invalid' in u or 'shop.other' in u for u in calls)


@pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '192.0.2.1', '::1'])
def test_unsafe_related_destination(monkeypatch, ip):
    import socket
    from legible.fetch import safety
    monkeypatch.setattr(safety.socket, 'getaddrinfo', lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))])
    _, calls = run(monkeypatch, {HOME: ('<a href="https://platform.widget.test/llms.txt">Canonical contract</a>', 'text/html')})
    assert 'https://platform.widget.test/llms.txt' not in calls


def test_https_required_for_new_origins(monkeypatch, public_dns):
    _, calls = run(monkeypatch, {HOME: ('<a href="http://platform.widget.test/llms.txt">Canonical API contract</a>', 'text/html')})
    assert 'http://platform.widget.test/llms.txt' not in calls


def test_embedded_rendered_mcp_configuration():
    text = ('Our MCP server provides tools. ' + 'Public information. ' * 40 +
            'Client configuration: { "mcpServers": { "widget": { "url": " https://mcp.widget.test " } } }')
    c, f = evaluate(text)
    assert 'mcp' in c.detected_types and f['mcp-discovery'].state == 'pass'


def test_sdk_error_attributes_are_machine_usable():
    text = 'API reference. SDK errors: except RequestError as err: if err.code == "invalid_input": correct the input. err.status gives the HTTP status.'
    assert evaluate(text)[1]['typed-errors'].state == 'pass'


def test_navigation_context_does_not_promote_every_link(monkeypatch):
    report, calls = run(monkeypatch, {HOME: ('<h1>MCP documentation</h1><nav><a href="/account">Create account</a>'
        '<a href="/pricing">Pricing</a></nav><a href="/mcp">MCP connection</a>', 'text/html')})
    assert HOME+'mcp' in calls
    assert HOME+'account' not in calls and HOME+'pricing' not in calls


def test_depth_is_bounded_even_when_every_page_emits_links(monkeypatch):
    pages = {HOME: ('<a href="/docs/0">API docs</a>', 'text/html')}
    pages.update({HOME+f'docs/{i}':(f'<a href="/docs/{i+1}">API docs</a>', 'text/html') for i in range(8)})
    _, calls = run(monkeypatch, pages)
    assert HOME+'docs/2' in calls and HOME+'docs/3' not in calls


def test_the_mcp_server_in_consumer_instructions_is_not_provider():
    c, f = evaluate('Credential setup: create files if absent. Set file permissions when the MCP server expects it. This configures third-party tools.')
    assert 'mcp' not in c.detected_types and f['mcp-discovery'].state == 'not_applicable'


def test_external_reference_docs_are_not_official_delegation(monkeypatch, public_dns):
    _, calls = run(monkeypatch, {HOME: ('<a href="/docs">Docs</a>', 'text/html'),
        HOME+'docs': ('<a href="https://protocol.other.test/specification">Model Context Protocol specification</a>'
                      '<a href="https://client.other.test/docs">Client documentation</a>', 'text/html')})
    assert not any('other.test' in u for u in calls)


def test_api_base_does_not_execute_published_api_path(monkeypatch, public_dns):
    _, calls = run(monkeypatch, {HOME: ('Read /llms.txt', 'text/html'),
        HOME+'llms.txt': ('API base URL: https://api.widget.test/v1/private-operation', 'text/plain')})
    assert 'https://api.widget.test/v1/private-operation' not in calls
    assert 'https://api.widget.test/' in calls


def test_credential_path_table_does_not_supply_connection_instructions():
    c, f = evaluate('Read credentials from your app connection. Common credential file locations | MCP Server | Credential path | tool | ~/.tool/ |')
    assert 'mcp' not in c.detected_types and f['mcp-discovery'].state == 'not_applicable'
