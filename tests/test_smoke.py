import io
import json
from dataclasses import asdict
from email.message import Message
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from legible import core
from legible.analyze.models import Finding
from legible.fetch import page
from legible.fetch.models import FetchObservation
from legible.main import main
from legible.output.writer import write_results


@pytest.mark.parametrize(('target', 'expected'), [
    ('example.com', 'https://example.com/'),
    (' EXAMPLE.com ', 'https://example.com/'),
    ('https://Example.com/docs?token=test#auth', 'https://example.com/'),
    ('http://example.com:8080/docs', 'http://example.com:8080/'),
    ('https://[::1]:8080/docs', 'https://[::1]:8080/'),
])
def test_normalize_target(target, expected):
    assert core.normalize_target(target) == expected


@pytest.mark.parametrize('target', [
    '', 'bad domain', 'ftp://example.com', 'https://',
    'https://user:secret@example.com', 'https://example.com:bad',
    'https://[broken',
])
def test_invalid_target(target):
    with pytest.raises(ValueError):
        core.normalize_target(target)


def response(body=b'<html>Hello</html>', content_type='text/html; charset=utf-8'):
    headers = Message()
    if content_type is not None:
        headers['Content-Type'] = content_type
    result = MagicMock()
    result.__enter__.return_value = result
    result.geturl.return_value = 'https://www.example.com/'
    result.status = 200
    result.headers = headers
    result.read.side_effect = io.BytesIO(body).read
    return result


def test_fetch_success(monkeypatch):
    monkeypatch.setattr(page, 'urlopen', lambda url: response())
    assert page.fetch_page('https://example.com/') == FetchObservation(
        'https://example.com/', 'https://www.example.com/', 200,
        'text/html; charset=utf-8', '<html>Hello</html>', None,
    )


@pytest.mark.parametrize(('body', 'content_type', 'text'), [
    (b'', None, ''),
    (b'caf\xe9', 'text/plain; charset=iso-8859-1', 'café'),
])
def test_fetch_empty_body_and_encoding(monkeypatch, body, content_type, text):
    monkeypatch.setattr(page, 'urlopen', lambda url: response(body, content_type))
    observation = page.fetch_page('https://example.com/')
    assert observation.text == text
    assert observation.content_type == content_type
    assert observation.error is None


def test_fetch_decode_failure_preserves_metadata(monkeypatch):
    monkeypatch.setattr(page, 'urlopen', lambda url: response(b'\xff'))
    observation = page.fetch_page('https://example.com/')
    assert observation.status == 200
    assert observation.final_url == 'https://www.example.com/'
    assert observation.text is None
    assert 'Could not read response:' in observation.error


def test_http_error_preserves_response_evidence(monkeypatch):
    headers = Message()
    headers['Content-Type'] = 'text/plain'
    error = HTTPError('https://www.example.com/', 404, 'Not Found',
                      headers, io.BytesIO(b'Unavailable'))
    def fail(url):
        raise error
    monkeypatch.setattr(page, 'urlopen', fail)
    assert page.fetch_page('https://example.com/') == FetchObservation(
        'https://example.com/', 'https://www.example.com/', 404,
        'text/plain', 'Unavailable', 'HTTP error: 404',
    )


@pytest.mark.parametrize(('error', 'message'), [
    (HTTPError('https://example.com/', 404, 'Not Found', Message(), None), 'HTTP error: 404'),
    (URLError('offline'), 'Could not reach URL: offline'),
])
def test_fetch_failure(monkeypatch, error, message):
    def fail(url):
        raise error
    monkeypatch.setattr(page, 'urlopen', fail)
    observation = page.fetch_page('https://example.com/')
    assert observation.requested_url == 'https://example.com/'
    assert observation.error == message
    if isinstance(error, URLError) and not isinstance(error, HTTPError):
        assert observation.final_url is None
        assert observation.status is None
        assert observation.content_type is None
        assert observation.text is None


def test_writer_adds_observations_and_renders_sources(tmp_path):
    observation = FetchObservation(
        "https://example.com/", "https://www.example.com/", 200,
        "text/html", "<p>Evidence</p>", None,
    )
    run_path = write_results(
        observation, [Finding('example', 'Example finding', 'unknown', observation.final_url, [], 'Example fix')], ['Example fix'], str(tmp_path),
    )
    report = json.loads((run_path / 'report.json').read_text())
    assert report == {
        'url': 'https://example.com/',
        'observations': [{key: value for key, value in asdict(observation).items() if key != 'metadata'}],
        'finding_count': 1, 'fix_count': 1,
        'findings': [asdict(Finding('example', 'Example finding', 'unknown', observation.final_url, [], 'Example fix'))], 'fixes': ['Example fix'],
    }
    markdown = (run_path / 'report.md').read_text()
    assert 'Example finding' in markdown
    assert '- Example fix' in markdown
    assert 'Source URL: https://www.example.com/' in markdown
    assert 'HTTP status: 200' in markdown
    assert 'Content type: text/html' in markdown


@pytest.mark.parametrize('args', [
    ['scan', 'example.com'], ['https://example.com/docs'],
])
def test_cli_writes_both_reports_without_claiming_a_pass(tmp_path, monkeypatch, capsys, args):
    monkeypatch.chdir(tmp_path)
    requested = []

    def fetch(url):
        requested.append(url)
        return FetchObservation(url, 'https://www.example.com/', 200,
                                'text/html', '<html><img src="photo.jpg"></html>')

    monkeypatch.setattr(core, 'fetch_page', fetch)
    assert main(args) == 0
    assert requested[0] == 'https://example.com/'
    assert len(requested) == 11
    report_path, = (tmp_path / 'runs').glob('*/report.json')
    report = json.loads(report_path.read_text())
    assert report['url'] == 'https://example.com/'
    assert report['observations'][0]['final_url'] == 'https://www.example.com/'
    assert len(report['findings']) == 7
    assert report['finding_count'] == 7
    markdown = report_path.with_suffix('.md').read_text()
    assert 'Assessed openapi' in markdown
    assert 'No issues found' not in markdown
    assert 'No fixes needed' not in markdown
    output = capsys.readouterr().out
    assert 'assessment complete' in output
    assert 'report.json' in output and 'report.md' in output


def test_cli_fetch_error_is_retained_in_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def fail(url):
        return FetchObservation(url, error='Could not reach URL: offline')

    monkeypatch.setattr(core, 'fetch_page', fail)
    assert main(['scan', 'example.com']) == 0
    report_path, = (tmp_path / 'runs').glob('*/report.json')
    report = json.loads(report_path.read_text())
    assert len(report['observations']) == 11
    assert all(f['state'] == ('not_applicable' if f['id'] == 'mcp-discovery' else 'unknown')
               for f in report['findings'])
    assert report['fixes'] == []


def test_cli_invalid_input_does_not_fetch(monkeypatch, capsys):
    def unexpected_fetch(url):
        pytest.fail('Invalid input must not reach the fetch layer')
    monkeypatch.setattr(core, 'fetch_page', unexpected_fetch)
    assert main(['scan', 'ftp://example.com']) == 1
    assert 'Error:' in capsys.readouterr().err


@pytest.mark.parametrize('args', [[], ['scan'], ['scan', 'example.com', 'extra']])
def test_cli_usage_errors(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_scan_passes_same_observation_to_analysis(tmp_path, monkeypatch):
    observation = FetchObservation('https://example.com/', text='Evidence')
    monkeypatch.setattr(core, 'fetch_page', lambda url: observation)
    seen = []
    def analyze(value, classification):
        seen.append(value)
        return []
    monkeypatch.setattr(core, 'analyze_surface', analyze)
    core.scan('example.com', str(tmp_path))
    assert seen[0].observations[0] is observation


def test_response_read_failure_retains_known_source(monkeypatch):
    fetched = response()
    fetched.read.side_effect = OSError('connection closed')
    monkeypatch.setattr(page, 'urlopen', lambda url: fetched)
    observation = page.fetch_page('https://example.com/')
    assert observation.final_url == 'https://www.example.com/'
    assert observation.status == 200
    assert observation.text is None
    assert observation.error == 'Could not read response: connection closed'


def test_writer_serializes_unavailable_values_as_null(tmp_path):
    observation = FetchObservation('https://example.com/', error='offline')
    path = write_results(observation, [], [], str(tmp_path))
    report = json.loads((path / 'report.json').read_text())
    assert report['observations'] == [{
        'requested_url': 'https://example.com/',
        'final_url': None, 'status': None, 'content_type': None,
        'text': None, 'error': 'offline',
    }]
