"""Synthetic browser requests without sockets or live network dependencies."""
import io
import json
from dataclasses import replace
from threading import Lock
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from legible import core, web
from legible.analyze.classification import SurfaceClassification
from legible.analyze.models import Finding, FindingEvidence
from legible.discover.surfaces import DiscoveredSurface, DiscoveryResult
from legible.fetch.models import FetchObservation
from legible.main import main
from legible.models import ScanReport
from legible.output.web import COPY, render_page


@pytest.fixture
def report():
    url = 'https://widget.example/docs'
    observation = FetchObservation(url, url, 200, 'text/plain', 'Public documentation')
    discovery = DiscoveryResult([observation], [DiscoveredSurface(url, 'published_link',
                                         'https://widget.example/', 'Documentation', 0)])
    states = ['pass', 'fail', 'unknown', 'not_applicable', 'fail', 'pass', 'unknown']
    findings = [Finding(id, 'Observed capability: Engine explanation.', state, url,
                        [FindingEvidence(0, url, 200, 'text/plain', None, 'API key: Use header X-Widget-Key.')],
                        'Engine-generated remediation.' if state == 'fail' else None)
                for id, state in zip(COPY, states)]
    return ScanReport(observation, discovery, SurfaceClassification('mixed', ['rest', 'mcp'],
                      'Published REST and MCP documentation.', []), findings, ['Engine-generated remediation.'])


def request(method='GET', path='/', data=None, headers=None, server=None):
    server = server or SimpleNamespace(form_token='test-token', scan_lock=Lock(), server_address=('127.0.0.1', 8765))
    body = urlencode(data or {}).encode()
    fields = {'Host': '127.0.0.1:8765', 'Content-Length': str(len(body)),
              'Content-Type': 'application/x-www-form-urlencoded'}
    fields.update(headers or {})
    raw = f'{method} {path} HTTP/1.1\r\n' + ''.join(f'{k}: {v}\r\n' for k, v in fields.items())
    reader, writer = io.BytesIO(raw.encode() + b'\r\n' + body), io.BytesIO()
    class Connection:
        def makefile(self, mode, *args):
            return reader
        def sendall(self, data):
            writer.write(data)
    web.WebHandler(Connection(), ('127.0.0.1', 1234), server)
    return writer.getvalue().decode()


def test_entry_and_assets():
    page = request()
    assert '200 OK' in page
    assert 'See your product the way software sees it.' in page
    assert 'name="domain"' in page and '>Scan</button>' in page
    assert 'test-token' in page
    assert 'text/css' in request(path='/style.css')
    assert 'Scanning…' in request(path='/app.js')
    assert '404' in request(path='/missing')


def test_group_states_evidence_and_surfaces(report):
    page = render_page('token', report, 'widget.example')
    for label in ['Discover', 'Access', 'Recover', 'Clear', 'Needs attention', 'Could not verify',
                  'Not applicable', 'REST API · MCP', 'Sources examined', 'Scan another domain',
                  'https://widget.example/docs', 'Use header X-Widget-Key.', 'Linked from']:
        assert label in page
    for finding in report.findings:
        card = page.split(f'id="{finding.id}"', 1)[1].split('</details>', 1)[0]
        assert ('Recommended fix' in card) == (finding.state == 'fail')
    assert '<details class="sources">' in page
    assert '<details class="finding pass"' in page  # Compact by default.


def test_unknown_never_displays_remediation_even_if_supplied(report):
    unknown = replace(report.findings[0], state='unknown', fix='UNSUPPORTED REMEDY')
    page = render_page('token', replace(report, findings=[unknown]))
    assert 'UNSUPPORTED REMEDY' not in page and 'Recommended fix' not in page


@pytest.mark.parametrize(('kind', 'types', 'expected'), [
    ('none', [], 'No software-facing surface established'),
    ('unknown', [], 'Surface could not be verified'),
    ('mixed', ['sdk', 'cli'], 'SDK · CLI'),
])
def test_surface_labels(report, kind, types, expected):
    classification = replace(report.classification, kind=kind, detected_types=types)
    assert expected in render_page('token', replace(report, classification=classification))


def test_remote_material_is_escaped(report):
    finding = replace(report.findings[0], title='<script>bad()</script>', evidence=[
        FindingEvidence(0, 'javascript:bad()', 200, 'text/plain', None, 'OpenAPI <img src=x onerror=bad()>')])
    page = render_page('token', replace(report, findings=[finding]), target='"><script>bad()</script>')
    assert '<script>bad()' not in page and '<img src=x' not in page
    assert 'href="javascript:' not in page
    assert '&lt;img' in page


def test_post_runs_real_pipeline_without_writing_reports(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    fetched = []
    def fetch(url):
        fetched.append(url)
        return FetchObservation(url, url, 200, 'text/html',
            '<p>REST API reference. Authenticate requests with an API key in the X-Widget-Key header. '
            'Create your API key in the developer dashboard.</p>')
    monkeypatch.setattr(core, 'fetch_page', fetch)
    response = request('POST', '/scan', {'domain': 'widget.example/path', 'token': 'test-token'})
    assert '200 OK' in response and 'REST API' in response
    assert fetched[0] == 'https://widget.example/' and len(fetched) <= 30
    assert all(f'id="{id}"' in response for id in COPY)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('target', ['', 'bad domain', 'ftp://widget.example', 'https://user:pass@widget.example'])
def test_invalid_domain_does_not_scan(monkeypatch, target):
    monkeypatch.setattr(core, 'scan_report', lambda target: pytest.fail('must not scan'))
    response = request('POST', '/scan', {'domain': target, 'token': 'test-token'})
    assert '400 Bad Request' in response and 'Provide a domain or an HTTP(S) URL' in response
    assert 'role="alert"' in response


@pytest.mark.parametrize(('headers', 'token'), [
    ({'Host': 'foreign.example'}, 'test-token'),
    ({'Origin': 'https://foreign.example'}, 'test-token'), ({}, 'wrong'), ({}, '非ASCII'),
])
def test_reject_foreign_requests(monkeypatch, headers, token):
    monkeypatch.setattr(core, 'scan_report', lambda target: pytest.fail('must not scan'))
    assert '403 Forbidden' in request('POST', '/scan', {'domain': 'widget.example', 'token': token}, headers)


def test_busy_and_failure_states(monkeypatch):
    server = SimpleNamespace(form_token='test-token', scan_lock=Lock(), server_address=('127.0.0.1', 8765))
    data = {'domain': 'widget.example', 'token': 'test-token'}
    server.scan_lock.acquire()
    assert '409 Conflict' in request('POST', '/scan', data, server=server)
    server.scan_lock.release()
    def broken(target):
        raise RuntimeError('private internals')
    monkeypatch.setattr(core, 'scan_report', broken)
    response = request('POST', '/scan', data, server=server)
    assert '500 Internal Server Error' in response and 'private internals' not in response
    assert not server.scan_lock.locked()


def test_web_command(monkeypatch):
    ports = []
    monkeypatch.setattr(web, 'serve', ports.append)
    assert main(['web']) == 0
    assert main(['web', '--port', '8888']) == 0
    assert ports == [8765, 8888]


def test_shared_result_preserves_cli_serialization(monkeypatch, tmp_path, report):
    monkeypatch.setattr(core, 'scan_report', lambda target: report)
    path = core.scan('widget.example', str(tmp_path))
    saved = json.loads((path / 'report.json').read_text())
    assert saved['findings'][0]['id'] == report.findings[0].id
    assert saved['classification']['detected_types'] == ['rest', 'mcp']
    assert (path / 'report.md').is_file()


def test_landing_and_compact_result_states(report):
    landing = render_page('token')
    assert '<section class="intro">' in landing
    assert 'id="scan-form" action="/scan" method="post" >' in landing
    assert 'id="scan-another"' not in landing
    result = render_page('token', report, 'widget.example')
    assert '<section class="intro">' not in result
    assert 'See your product the way software sees it.' not in result
    assert 'aria-controls="scan-form" aria-expanded="false"' in result
    assert 'hidden class="compact-form"' in result
    assert 'value="widget.example"' in result
    assert 'class="counts"' not in result
    assert 'Some conclusions could not be verified' not in result
    assert 'This report describes published information' not in result
    assert result.index('Sources examined') < result.index('<strong>Scope:</strong>') < result.index('</article>')
    assert result.count('<footer>') == 1


@pytest.mark.parametrize('types,phrase', [
    (['rest'], 'a REST API'), (['mcp'], 'an MCP surface'),
    (['sdk'], 'an SDK'), (['cli'], 'a CLI'),
    (['rest', 'mcp'], 'a REST API and an MCP surface'),
    (['rest', 'sdk', 'cli'], 'a REST API, an SDK, and a CLI'),
])
def test_detected_interface_copy(report, types, phrase):
    report = replace(report, classification=replace(report.classification, detected_types=types))
    page = render_page('token', report)
    assert 'Detected public interface' in page
    assert f'Legible found public documentation describing {phrase}.' in page
    assert 'Other integration surfaces may exist but were not confirmed in the public material examined.' in page


def test_sections_cards_and_stable_order(report):
    from legible.output.web import GROUPS
    report = replace(report, findings=[replace(f, state='unknown', fix=None) for f in reversed(report.findings)])
    page = render_page('token', report)
    assert page.count('<details class="finding ') == 7
    assert page.count('How to read this report') == 1
    assert page.index('How to read this report') < page.index('<h3>Discover</h3>')
    for name, description, ids in GROUPS:
        section = page.split(f'<h3>{name}</h3>')[1].split('<section class="group">')[0]
        assert description in section
        positions = [section.index(f'id="{id}"') for id in ids]
        assert positions == sorted(positions)
        for id in COPY:
            assert (f'id="{id}"' in section.split('<details class="sources">')[0]) == (id in ids)
    assert 'Machine-readable errors' in page and 'Safe retry guidance' in page
    assert 'Can an agent reliably interpret a failed response?' in page
    assert 'Can an agent determine whether, when, and how to try again?' in page
    assert 'consistent, machine-readable error format' in page
    assert 'guidance for avoiding duplicate operations' in page
    assert 'it may guess the wrong response' in page
    assert 'Never retrying can cause an agent to abandon' in page
    assert 'id="structured-errors"' not in page


@pytest.mark.parametrize('state', ['fail', 'unknown', 'pass', 'not_applicable'])
def test_outcome_actions_for_every_check(report, state):
    from legible.output.web import VERIFY, finding_card
    for original in report.findings:
        finding = replace(original, state=state, fix='Existing engine remedy.')
        card = finding_card(finding, report)
        assert ('Recommended fix' in card) == (state == 'fail')
        assert ('Existing engine remedy.' in card) == (state == 'fail')
        assert ('What would verify this' in card) == (state == 'unknown')
        assert (VERIFY[finding.id] in card) == (state == 'unknown')
        assert 'Engine explanation.' in card
    failure = replace(report.findings[0], state='fail', fix=None)
    assert 'Recommended fix' not in finding_card(failure, report)


def test_fix_first_limit_priority_and_links(report):
    findings = [replace(f, state='fail', fix=f'Remedy for {f.id}.') for f in reversed(report.findings)]
    page = render_page('token', replace(report, findings=findings))
    summary = page.split('<section class="fix-first">')[1].split('</section>')[0]
    assert summary.count('<li>') == 3
    assert summary.index('#auth-mechanism') < summary.index('#key-issuance') < summary.index('#openapi')
    for id in ['auth-mechanism', 'key-issuance', 'openapi']:
        assert f'href="#{id}"' in summary and f'Remedy for {id}.' in summary
        assert f'id="{id}"' in page
    assert page.index('How to read this report') < page.index('Fix first') < page.index('<h3>Discover</h3>')
    findings = [replace(f, state='unknown') if f.id != 'retry-guidance' else f for f in findings]
    page = render_page('token', replace(report, findings=findings))
    summary = page.split('<section class="fix-first">')[1].split('</section>')[0]
    assert summary.count('<li>') == 1 and '#retry-guidance' in summary
    assert '#auth-mechanism' not in summary
    page = render_page('token', replace(report, findings=[replace(f, state='unknown') for f in findings]))
    assert 'Fix first' not in page and 'Findings to review' not in page


def test_cards_order_by_state_then_check_order(report):
    states = {'openapi': 'pass', 'llms-txt': 'unknown', 'mcp-discovery': 'fail',
              'auth-mechanism': 'not_applicable', 'key-issuance': 'pass',
              'typed-errors': 'unknown', 'retry-guidance': 'fail'}
    page = render_page('token', replace(report, findings=[replace(f, state=states[f.id]) for f in report.findings]))
    for ids in [('mcp-discovery', 'llms-txt', 'openapi'), ('key-issuance', 'auth-mechanism'), ('retry-guidance', 'typed-errors')]:
        positions = [page.index(f'id="{id}"') for id in ids]
        assert positions == sorted(positions)


def test_local_fetch_allowed_by_csp():
    assert "connect-src 'self';" in request()


def test_browser_interactions():
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which('node')
    if node is None:
        pytest.skip('Optional Node runtime unavailable for client interaction harness')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, 'tests/web_interactions.cjs'], cwd=root, check=True, capture_output=True, text=True)
