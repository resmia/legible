"""A public guide is shared evidence, including when it documents denied requests."""
from dataclasses import replace
import io
from email.message import Message

import pytest
from legible.analyze.analyzer import analyze_surface
from legible.analyze.classification import classify_surface, _text
from legible.discover.surfaces import DiscoveryResult, DiscoveredSurface, discover_surfaces
from legible.fetch.models import FetchObservation, FetchMetadata
from legible.fetch import page

URL = 'https://docs.widget.test/guide'
GUIDE = '''<html><title>Public API reference</title><h1>API reference</h1>
<h2>Authentication</h2><p>Authenticate requests using an API key.</p>
<pre>Authorization: Bearer WIDGET_API_KEY</pre>
<h2>Obtain a key</h2><p>Open API access in your dashboard and create a key. The secret is shown once.</p>
<h2>Errors</h2><pre>{"error":{"code":"invalid_input","message":"Check input","details":[]}}</pre>
<table><tr><td>403</td><td>Access denied</td><td>Check permissions.</td></tr></table>
<h2>Rate limits</h2><p>For HTTP 429, honor the Retry-After header before retrying.</p>
<p>For HTTP 503, retry with capped exponential backoff and jitter.</p>
<p>Do not retry unchanged validation or authentication failures.</p></html>'''


def observation(text=GUIDE, **kwargs):
    return FetchObservation(URL, URL, 200, 'text/html', text, **kwargs)


def evaluate(observations, reason='published_link', label='Documentation'):
    d = DiscoveryResult(observations, [DiscoveredSurface(o.requested_url, reason, None, label, i) for i,o in enumerate(observations)])
    return d, {f.id:f for f in analyze_surface(d, classify_surface(d))}


@pytest.mark.parametrize('reason,label', [('homepage','Home'), ('public_file','OpenAPI specification'), ('published_link','Retry instructions')])
def test_one_document_shared_by_all_checks(reason, label):
    o = observation()
    d, findings = evaluate([o], reason, label)
    assert {f.id:f.state for f in findings.values()} == {
        'openapi':'unknown', 'auth-mechanism':'pass', 'key-issuance':'pass',
        'llms-txt':'unknown', 'typed-errors':'pass', 'retry-guidance':'pass', 'mcp-discovery':'not_applicable'}
    for key in ['auth-mechanism','key-issuance','typed-errors','retry-guidance']:
        assert any(e.observation_index == 0 for e in findings[key].evidence)
    assert any('Authorization: Bearer' in e.excerpt for e in findings['auth-mechanism'].evidence)
    assert any('create a key' in e.excerpt for e in findings['key-issuance'].evidence)
    assert o.text == GUIDE and 'Rate limits' in o.document.text
    assert any(b.kind == 'pre' and 'invalid_input' in b.text for b in o.document.blocks)


@pytest.mark.parametrize('text', ['Access denied', '<title>Access denied</title><h1>Access denied</h1>', 'Verify you are human', 'Sign in to continue'])
def test_real_blocked_pages_remain_unavailable(text):
    o = observation(text)
    assert _text(o) is None
    assert o.availability == 'fetch_rejected_or_failed'


def test_head_cannot_be_evidence_or_suppress_get():
    probe = observation(metadata=FetchMetadata(method='HEAD'))
    assert _text(probe) is None
    calls = []
    def fetch(url):
        calls.append(url)
        return observation() if url == URL else FetchObservation(url, status=404, error='HTTP error: 404')
    result = discover_surfaces(probe, fetch)
    assert calls.count(URL) == 1
    assert result.observations[0] is probe
    assert any(o.text == GUIDE and o.availability == 'available' for o in result.observations)


def test_head_response_body_is_never_retained():
    r = io.BytesIO(GUIDE.encode()); r._method = 'HEAD'; r.status = 200
    r.geturl = lambda: URL; r.headers = Message(); r.headers['Content-Type'] = 'text/html'
    o = page._observe_response(URL,r)
    assert o.text is None and o.metadata.method == 'HEAD' and r.tell() == 0


def test_limit_rejection_records_truncation(monkeypatch):
    r = io.BytesIO(b'x'*20); r.status = 200; r.geturl = lambda: URL
    r.headers = Message(); r.headers['Content-Type'] = 'text/html'
    monkeypatch.setattr(page,'MAX_RESPONSE_BYTES',8)
    o = page._observe_response(URL,r)
    assert o.text is None and o.metadata.truncated
    assert o.metadata.encoded_bytes == 9 and o.metadata.decoded_bytes == 0
    assert o.availability == 'body_truncated'


def test_duplicate_thin_observation_does_not_replace_rich_evidence():
    rich = observation()
    thin = replace(rich, requested_url=URL+'#alias',text='<p>Sign in</p>')
    d, findings = evaluate([rich,thin])
    assert rich.canonical_url == thin.canonical_url
    assert d.observations[0] is rich and len(d.observations) == 2
    assert findings['typed-errors'].state == findings['retry-guidance'].state == 'pass'


@pytest.mark.parametrize('status,media,redirect', [(403,None,None), (405,'application/octet-stream',None), (200,'application/json','https://elsewhere.widget.test/')])
def test_head_rejection_or_misleading_metadata_does_not_change_get(monkeypatch, status, media, redirect):
    from unittest.mock import MagicMock
    probe = FetchObservation(URL, redirect or URL, status, media, None,
        metadata=FetchMetadata(method='HEAD'))
    methods = []
    def open_request(req, **kwargs):
        methods.append(req.get_method())
        r = io.BytesIO(GUIDE.encode()); r.status = 200; r.geturl = lambda: URL
        r.headers = Message(); r.headers['Content-Type'] = 'text/html'
        return r
    opener = MagicMock(); opener.open.side_effect = open_request
    monkeypatch.setattr(page,'build_opener',lambda *args:opener)
    result = discover_surfaces(probe, lambda url: page.fetch_page(url) if url == URL else FetchObservation(url,status=404,error='missing'))
    assert methods == ['GET']
    rich = next(o for o in result.observations if o.availability == 'available')
    assert rich.text == GUIDE and rich.metadata.method == 'GET'
    assert rich.metadata.decoded_bytes == len(GUIDE.encode())


def test_optional_metadata_serialization(tmp_path):
    import json
    from legible.output.writer import write_results
    from legible.fetch.models import RedirectObservation
    o = observation(metadata=FetchMetadata(redirects=(RedirectObservation(URL+'/old', URL, 302),),decoded_bytes=len(GUIDE.encode())))
    report = json.loads((write_results(o,[],[],str(tmp_path))/'report.json').read_text())
    saved = report['observations'][0]
    assert saved['text'] == GUIDE and saved['canonical_url'] == URL
    assert saved['metadata']['redirects'] == [{'source_url': URL+'/old','target_url': URL,'status':302}]
    assert saved['metadata']['truncated'] is False


def test_diagnostics_distinguish_causes():
    from legible.analyze.diagnostics import diagnose_evidence
    objects = [observation(), observation(text='',metadata=FetchMetadata(method='HEAD')),
        observation(text=None,metadata=FetchMetadata(truncated=True)),
        replace(observation(),content_type='image/png'),
        replace(observation(),status=403,error='HTTP error: 403')]
    d, findings = evaluate(objects)
    diagnostics = diagnose_evidence(d,findings.values(),['https://docs.widget.test/undiscovered'])
    assert [o.availability for o in diagnostics.observations] == ['available','body_unavailable','body_truncated','unsupported_response','fetch_rejected_or_failed']
    assert len(diagnostics.observations[0].evaluator_checks) == 7
    assert not diagnostics.observations[1].evaluator_checks
    assert diagnostics.unexamined_urls == (('https://docs.widget.test/undiscovered','url_not_discovered'),)
    assert 'evidence_examined_not_recognized' in dict(diagnostics.unknown_reasons)['openapi']
    d.observations.extend([observation()] * 25)
    d.pending_urls = ['https://docs.widget.test/pending']
    assert 'budget_exhausted' in dict(diagnose_evidence(d,findings.values()).unknown_reasons)['openapi']


@pytest.mark.parametrize('prefix', ['Example only:', 'Not supported:', 'Planned:'])
def test_hypothetical_bearer_header_is_not_positive(prefix):
    _, findings = evaluate([observation(f'<h1>API reference</h1><p>{prefix} Authorization: Bearer DEMO</p>')])
    assert findings['auth-mechanism'].state != 'pass'


def test_code_words_alone_are_not_credential_instructions():
    _, findings = evaluate([observation('<h1>API reference</h1><p>Authenticate API requests with an API key.</p>'
        '<pre>// create key dashboard API access example</pre>')])
    assert findings['key-issuance'].state != 'pass'


def test_missing_declared_body_records_truncation():
    r = io.BytesIO(b''); r.status = 200; r.geturl = lambda: URL
    r.headers = Message(); r.headers['Content-Type'] = 'text/html'; r.headers['Content-Length'] = '100'
    o = page._observe_response(URL, r)
    assert o.metadata.truncated and o.text is None
    assert o.availability == 'body_truncated'
