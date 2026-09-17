"""Presentation selection retains the complete shared result and source list."""
from copy import deepcopy
from dataclasses import replace
from html import escape
import json

import pytest

from legible.analyze.classification import SurfaceClassification
from legible.analyze.models import Finding, FindingEvidence
from legible.discover.surfaces import DiscoveredSurface, DiscoveryResult
from legible.fetch.models import FetchObservation
from legible.models import ScanReport
from legible.output.evidence import EXCERPT_LIMIT, select_evidence
from legible.output.web import finding_card, render_report
from legible.output.writer import write_results


def make_report(check, pages, state='pass'):
    observations = [FetchObservation('https://example.com'+path, 'https://example.com'+path,
                                    status, media, text, None if status == 200 else 'Unavailable')
                    for path, text, media, status in pages]
    evidence = [FindingEvidence(i, o.final_url, o.status, o.content_type, o.error, o.text)
                for i, o in enumerate(observations)]
    finding = Finding(check, 'Capability: Evidence explanation.', state, observations[0].final_url,
                      evidence, 'Engine remedy.' if state == 'fail' else None)
    discovery = DiscoveryResult(observations, [DiscoveredSurface(o.final_url, 'published_link',
                                observations[0].final_url, '', i) for i, o in enumerate(observations)])
    return ScanReport(observations[0], discovery, SurfaceClassification('rest', ['rest'], '', []), [finding], [])


@pytest.mark.parametrize('check,path,text,media', [
    ('openapi', '/openapi.json', '{"openapi":"3.1.0","info":{},"paths":{}}', 'application/json'),
    ('llms-txt', '/llms.txt', '[API reference](/docs)', 'text/plain'),
    ('auth-mechanism', '/auth', 'API authentication: send Authorization: Bearer TOKEN.', 'text/html'),
    ('key-issuance', '/keys', 'Create your API key in dashboard settings.', 'text/html'),
    ('typed-errors', '/errors', 'Error object: code string stable identifier; message string; param string.', 'text/html'),
    ('retry-guidance', '/retry', 'Wait the Retry-After seconds before retrying.', 'text/html'),
    ('mcp-discovery', '/.well-known/mcp-server-card', '{"name":"Widget MCP","transport":{"url":"https://example.com/mcp"}}', 'application/json'),
    ('mcp-discovery', '/mcp', 'MCP server endpoint: connect to https://example.com/mcp.', 'text/html'),
])
def test_direct_evidence_outranks_broad_pages(check, path, text, media):
    report = make_report(check, [('/', 'API documentation navigation: auth errors retry MCP OpenAPI llms.txt.', 'text/html', 200),
                                ('/docs', 'API reference. Authentication uses API keys.', 'text/html', 200),
                                (path, text, media, 200)])
    selected = select_evidence(report.findings[0], report)
    assert selected[0].source_url.endswith(path)
    assert len(selected) <= 2


def test_excerpt_limits_nonmutation_complete_sources_and_serialization(tmp_path):
    report = make_report('typed-errors', [(f'/errors/{i}', 'Error object: code string stable identifier. '
                        + '<img src=x onerror=bad()> '*1000, 'text/html', 200) for i in range(8)])
    before = deepcopy(report)
    path = write_results(report.homepage, report.findings, [], str(tmp_path/'before'),
                         discovery=report.discovery, classification=report.classification)
    original_json = (path/'report.json').read_text()
    original_md = (path/'report.md').read_text()
    selected = select_evidence(report.findings[0], report)
    assert all(len(e.excerpt) <= EXCERPT_LIMIT and e.excerpt.endswith('…') for e in selected)
    card = finding_card(report.findings[0], report)
    assert 1 <= card.count('<blockquote>') <= 3
    assert '<img' not in card and '&lt;img' in card
    page = render_report(report)
    sources = page.split('<details class="sources">')[1]
    assert sources.count('<h4>Requested URL</h4>') == 8
    assert escape(report.discovery.observations[0].text) in sources
    assert '<details class="sources" open' not in page
    assert report == before
    path = write_results(report.homepage, report.findings, [], str(tmp_path/'after'),
                         discovery=report.discovery, classification=report.classification)
    assert (path/'report.json').read_text() == original_json
    assert (path/'report.md').read_text() == original_md
    assert len(json.loads(original_json)['observations']) == 8


def test_unknown_relevant_attempts_and_no_remedy():
    report = make_report('openapi', [('/', 'Welcome', 'text/html', 200),
                        ('/openapi.json', '', 'application/json', 503)], 'unknown')
    finding = replace(report.findings[0], fix='Do not show this')
    selected = select_evidence(finding, report)
    assert len(selected) == 1 and selected[0].status == 503
    card = finding_card(finding, report)
    assert 'How to fix' not in card and 'Do not show this' not in card


def test_not_applicable_compact_and_failure_has_engine_remedy():
    report = make_report('mcp-discovery', [('/', 'API reference '*1000, 'text/html', 200)], 'not_applicable')
    card = finding_card(report.findings[0], report)
    assert '<blockquote>' not in card and 'Why this matters' not in card
    assert len(card) < 600
    assert 'Engine remedy.' in finding_card(replace(report.findings[0], state='fail', fix='Engine remedy.'), report)


def test_unknown_evidence_is_capped_at_three_relevant_attempts():
    report = make_report('openapi', [(f'/openapi-{i}.json', '', 'application/json', 503)
                                    for i in range(7)], 'unknown')
    selected = select_evidence(report.findings[0], report)
    assert len(selected) == 3
    assert finding_card(report.findings[0], report).count('<li>') == 3
    assert len(report.findings[0].evidence) == 7
