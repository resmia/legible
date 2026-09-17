"""Deterministic V1 evidence, applicability, and bounded end-to-end checks."""
import json
from copy import deepcopy

import pytest

from legible import core
from legible.analyze.analyzer import analyze_surface
from legible.analyze.classification import classify_surface
from legible.discover.surfaces import discover_surfaces, _priority
from legible.fetch.models import FetchObservation
from legible.fix.fixer import create_fixes

HOME = 'https://example.com/'
REST = 'API reference. '
AUTH = 'API requests authenticate using API keys. Create an API key in the dashboard. '
ERRORS = 'HTTP 400 error response: {"error": {"code": "invalid_parameter", "type": "validation_error"}}. '
RETRIES = 'For 429 responses, wait the number of seconds in the Retry-After header before retrying. '
SPEC = json.dumps({'openapi': '3.1.0', 'info': {}, 'paths': {}})
IDS = {'openapi', 'auth-mechanism', 'key-issuance', 'llms-txt', 'typed-errors', 'retry-guidance', 'mcp-discovery'}


def obs(url, body, media='text/html', status=200):
    return FetchObservation(url, url, status, media, body, None if status == 200 else f'HTTP error: {status}')


def evaluate(body=REST, pages=None, pending=()):
    pages = pages or {}
    discovery = discover_surfaces(obs(HOME, body), lambda u: pages.get(u, obs(u, 'Missing', status=404)))
    discovery.pending_urls.extend(pending)
    before = deepcopy(discovery)
    findings = analyze_surface(discovery, classify_surface(discovery))
    assert discovery == before
    assert findings == analyze_surface(discovery, classify_surface(discovery))
    assert {f.id for f in findings} == IDS
    assert all(f.evidence for f in findings)
    assert all(f.fix is None for f in findings if f.state != 'fail')
    return {f.id: f for f in findings}


@pytest.mark.parametrize('url', [HOME+'llms.txt', HOME+'docs/llms.txt', 'https://docs.example.com/llms.txt'])
def test_published_index(url):
    result = evaluate(REST+f'<a href="{url}">Machine-readable documentation index</a>', {
        url: obs(url, '# Developer docs\n[API reference](/reference)', 'text/plain')})
    finding = result['llms-txt']
    assert finding.state == 'pass'
    assert any(e.source_url == url and '[API reference]' in e.excerpt for e in finding.evidence)


@pytest.mark.parametrize('status', [403, 404, 503])
def test_advertised_index_unavailable(status):
    url = HOME+'docs/llms.txt'
    finding = evaluate(REST+f'<a href="{url}">llms.txt</a>', {
        url: obs(url, 'unavailable', status=status)})['llms-txt']
    assert finding.state == 'unknown'
    assert any(e.source_url == url and e.status == status for e in finding.evidence)


@pytest.mark.parametrize('body,media', [
    ('We talk about llms.txt and documentation.', 'text/plain'),
    ('<h1>Welcome</h1><a href="/docs">API documentation</a>', 'text/html'),
    ('[Buy shoes](/shop)', 'text/plain'),
    ('', 'text/plain'),
])
def test_unusable_index_is_not_positive(body, media):
    url = HOME+'llms.txt'
    assert evaluate(REST, {url: obs(url, body, media)})['llms-txt'].state == 'unknown'


def test_index_absence_needs_coverage_and_applicability():
    assert evaluate()['llms-txt'].state == 'fail'
    assert evaluate(pending=[HOME+'docs'])['llms-txt'].state == 'unknown'
    assert evaluate('A bakery.')['llms-txt'].state == 'not_applicable'
    docs = 'https://docs.example.com/'
    assert evaluate(REST, {docs: obs(docs, 'API reference.')})['llms-txt'].state == 'unknown'


@pytest.mark.parametrize('body', [ERRORS, 'Error response: {"code": "invalid_input", "type": "validation"}.',
    'The error code INVALID_INPUT identifies an invalid parameter.'])
def test_structured_errors_pass(body):
    assert evaluate(REST+body)['typed-errors'].state == 'pass'


@pytest.mark.parametrize('media', ['application/json', 'application/problem+json'])
def test_openapi_error_schema_with_local_reference(media):
    document = {'openapi': '3.1.0', 'info': {}, 'paths': {'/widgets': {'get': {'responses': {
        '400': {'content': {media: {'schema': {'$ref': '#/components/schemas/Error'}}}}}}}},
        'components': {'schemas': {'Error': {'type': 'object', 'properties': {'code': {'type': 'string'}}}}}}
    url = HOME+'openapi.json'
    finding = evaluate(REST, {url: obs(url, json.dumps(document), 'application/json')})['typed-errors']
    assert finding.state == 'pass'
    assert any('GET /widgets: HTTP 400' in e.excerpt for e in finding.evidence)
    document['components']['schemas']['Error'] = {'$ref': '#/components/schemas/Error'}
    assert evaluate(REST, {url: obs(url, json.dumps(document), 'application/json')})['typed-errors'].state == 'unknown'


@pytest.mark.parametrize('body', ['Errors may occur.', 'Errors. HTTP 400, 401, 500.',
    'try { request(); } catch (error) { console.log({"error": "oops"}); }',
    '<script>Error response: {"code":"invalid"}</script>'])
def test_error_false_positives(body):
    assert evaluate(REST+body)['typed-errors'].state != 'pass'


@pytest.mark.parametrize('body', [RETRIES, 'Retry transient failures with exponential backoff.',
    'Reuse the same idempotency key to safely retry a request.',
    'The SDK automatically retries 503 responses after a delay.'])
def test_actionable_retry(body):
    assert evaluate(REST+body)['retry-guidance'].state == 'pass'


@pytest.mark.parametrize('body', ['Rate limits apply.', 'HTTP 429 means too many requests.',
    'Requests support idempotency keys.', 'Try again later for amazing offers.',
    'Exponential backoff is planned.', 'Retry-After is a topic in our blog.'])
def test_retry_false_positives(body):
    assert evaluate(REST+body)['retry-guidance'].state != 'pass'


@pytest.mark.parametrize('check,label', [('typed-errors', 'Errors'), ('retry-guidance', 'Rate limits')])
def test_unavailable_or_pending_relevant_docs_are_unknown(check, label):
    url = HOME+'docs/errors' if check == 'typed-errors' else HOME+'docs/rate-limits'
    finding = evaluate(REST+f'<a href="{url}">{label}</a>', {url: obs(url, '', status=503)})[check]
    assert finding.state == 'unknown'
    assert any(e.source_url == url and e.status == 503 for e in finding.evidence)
    assert evaluate(REST+'HTTP 400 error response is plain text. Rate limits apply.', pending=[url])[check].state == 'unknown'


def test_failures_require_examined_semantics():
    result = evaluate(REST+'HTTP 400 error response is plain text. Rate limits apply.')
    assert result['typed-errors'].state == result['retry-guidance'].state == 'fail'
    result = evaluate(REST+'Errors may occur.')
    assert result['typed-errors'].state == 'unknown'
    assert create_fixes([result['typed-errors']]) == []


@pytest.mark.parametrize('body', ['MCP server: connect to https://example.com/mcp.',
    'MCP server: configure the client command npx @example/server.'])
def test_mcp_connection_instructions(body):
    assert evaluate(body)['mcp-discovery'].state == 'pass'


def test_mcp_card():
    url = HOME+'.well-known/mcp-server-card'
    body = json.dumps({'name': 'Fixture MCP', 'transport': {'type': 'streamable-http', 'url': 'https://example.com/mcp'}})
    assert evaluate('Developer tools.', {url: obs(url, body, 'application/json')})['mcp-discovery'].state == 'pass'


def test_mcp_config():
    url = HOME+'mcp'
    body = json.dumps({'mcpServers': {'fixture': {'command': 'npx', 'args': ['@example/server']}}})
    assert evaluate(f'<a href="{url}">MCP setup</a>', {url: obs(url, body, 'application/json')})['mcp-discovery'].state == 'pass'


def test_mcp_absence_and_incomplete_coverage():
    body = 'MCP server: configure your client connection.'
    assert evaluate(body)['mcp-discovery'].state == 'fail'
    assert evaluate(body, pending=[HOME+'mcp/setup'])['mcp-discovery'].state == 'unknown'
    assert evaluate(REST)['mcp-discovery'].state == 'not_applicable'
    assert evaluate('Our MCP server is planned.')['mcp-discovery'].state == 'not_applicable'


def test_local_cli_does_not_inherit_rest_assumptions():
    result = evaluate('CLI command-line tool: pip install fixture-cli. Processes local files.')
    assert all(result[id].state == 'not_applicable' for id in ('openapi', 'typed-errors', 'retry-guidance', 'mcp-discovery'))


@pytest.mark.parametrize('check,url,label', [
    ('typed-errors', '/errors', 'API error handling'),
    ('retry-guidance', '/limits', '429 backoff'),
    ('retry-guidance', '/idempotency', 'Safe retries'),
])
def test_unresolved_evidence_priorities(check, url, label):
    assert _priority(HOME+url, label, 'published_link', {check}) < _priority(HOME+url, label, 'published_link', set())


def run_scan(monkeypatch, output, unresolved=False):
    pages = {
        HOME: obs(HOME, REST+AUTH+'<a href="/docs">Docs</a>'),
        HOME+'docs': obs(HOME+'docs', '<a href="/llms.txt">Index</a>'+''.join(
            f'<a href="/docs/page-{i}">API documentation</a>' for i in range(45))),
        HOME+'llms.txt': obs(HOME+'llms.txt', '[OpenAPI](/openapi.json)\n[Errors](/errors)\n[MCP setup](/mcp)', 'text/plain'),
        HOME+'openapi.json': obs(HOME+'openapi.json', SPEC, 'application/json'),
        HOME+'errors': obs(HOME+'errors', ERRORS+('' if unresolved else RETRIES)),
        HOME+'mcp': obs(HOME+'mcp', 'MCP server: connect to https://example.com/mcp.'),
    }
    calls = []
    def fetch(url):
        calls.append(url)
        return pages.get(url, obs(url, 'API documentation is incomplete.' if '/docs/page-' in url else 'Missing',
                                  status=200 if '/docs/page-' in url else 404))
    monkeypatch.setattr(core, 'fetch_page', fetch)
    path = core.scan(HOME, str(output))
    report = json.loads((path/'report.json').read_text())
    markdown = (path/'report.md').read_text()
    assert report['finding_count'] == 7
    assert {f['id'] for f in report['findings']} == IDS
    assert len(calls) <= 30
    assert report['discovery']['max_fetches'] == 30
    for finding in report['findings']:
        assert finding['evidence']
        assert finding['id'] in markdown and finding['state'] in markdown
        for evidence in finding['evidence']:
            observation = report['observations'][evidence['observation_index']]
            assert evidence['source_url'] == observation['final_url']
            assert evidence['source_url'] in markdown
    if unresolved:
        assert len(calls) == 30
        retry = next(f for f in report['findings'] if f['id'] == 'retry-guidance')
        assert retry['state'] == 'unknown' and retry['fix'] is None
    else:
        assert len(calls) == 10
        assert report['classification']['kind'] == 'mixed'
        assert all(f['state'] == 'pass' for f in report['findings'])
        assert report['fixes'] == []
    assert report['discovery']['pending_urls']
    return path, len(calls)


@pytest.mark.parametrize('unresolved', [False, True])
def test_seven_check_end_to_end(monkeypatch, tmp_path, unresolved):
    run_scan(monkeypatch, tmp_path, unresolved)


def test_explicit_mcp_without_connection_vocabulary_is_established():
    assert evaluate('Our MCP server provides tools for widgets.')['mcp-discovery'].state == 'fail'


def test_blog_about_index_is_not_an_index():
    url = HOME+'blog/llms.txt-introduction'
    finding = evaluate(REST+f'<a href="{url}">About llms.txt</a>', {
        url: obs(url, 'An article about llms.txt. [API docs](/docs)', 'text/plain')})['llms-txt']
    assert finding.state != 'pass'


def test_equivalent_published_markdown_index():
    url = HOME+'agent-guide.md'
    assert evaluate(REST+f'<a href="{url}">Machine-readable documentation index</a>', {
        url: obs(url, '# Docs\n[API reference](/reference)', 'text/markdown')})['llms-txt'].state == 'pass'


def test_negative_retry_instruction_does_not_pass():
    assert evaluate(REST+'We do not support exponential backoff.')['retry-guidance'].state != 'pass'


def test_success_schema_is_not_error_schema():
    document = {'openapi': '3.1.0', 'info': {}, 'paths': {'/widgets': {'get': {'responses': {
        '200': {'description': 'Widget including error statistics', 'content': {
            'application/json': {'schema': {'type': 'object', 'properties': {'type': {'type': 'string'}}}}}}}}}}}
    url = HOME+'openapi.json'
    assert evaluate(REST, {url: obs(url, json.dumps(document), 'application/json')})['typed-errors'].state == 'unknown'


def test_error_schema_external_reference_is_not_fetched_or_assumed():
    document = {'openapi': '3.1.0', 'info': {}, 'paths': {'/widgets': {'get': {'responses': {
        '400': {'content': {'application/json': {'schema': {'$ref': 'https://external.example/error.json'}}}}}}}}}
    url = HOME+'openapi.json'
    assert evaluate(REST, {url: obs(url, json.dumps(document), 'application/json')})['typed-errors'].state == 'unknown'


def test_local_mcp_docs_link_does_not_imply_network_transport():
    body = 'MCP server: configure your client command npx @example/server. More docs at https://example.com/docs.'
    result = evaluate(body)
    assert result['typed-errors'].state == result['retry-guidance'].state == 'not_applicable'


def test_unavailable_mcp_setup_is_unknown_with_provenance():
    url = HOME+'mcp/setup'
    finding = evaluate('MCP server: configure your client. '+f'<a href="{url}">MCP setup</a>', {
        url: obs(url, 'Unavailable', status=503)})['mcp-discovery']
    assert finding.state == 'unknown'
    assert any(e.source_url == url and e.status == 503 for e in finding.evidence)


def test_unrecognized_mcp_artifact_remains_inconclusive():
    url = HOME+'.well-known/mcp-server-card'
    result = evaluate('MCP server: configure your client.', {
        url: obs(url, '{"custom_connection": "opaque"}', 'application/json')})
    assert result['mcp-discovery'].state == 'unknown'


@pytest.mark.parametrize('text,check', [
    ('Exponential backoff is a computer science concept.', 'retry-guidance'),
    ('A planned error code INVALID_REQUEST identifies failures.', 'typed-errors'),
])
def test_concept_mentions_are_not_documented_behavior(text, check):
    assert evaluate(REST+text)[check].state != 'pass'
