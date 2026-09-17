import io
import json
from urllib.error import HTTPError, URLError

import pytest

from legible import core
from legible.analyze.analyzer import analyze_page
from legible.fetch import page
from legible.fix.fixer import create_fixes
from legible.main import main
from legible.output.writer import write_results


@pytest.mark.parametrize("html", [
    '<html><body><img src="photo.jpg"></body></html>',
    '<html lang="en"><head><title>Hello</title>'
    '<meta name="description" content="Example"></head>'
    '<body><h1>Welcome</h1><img src="photo.jpg" alt="Mountain"></body></html>',
    '<p>API key, OpenAPI, Retry-After, MCP</p>',
    '',
])
def test_scaffold_does_not_make_findings_from_html(html):
    assert analyze_page(html) == []


def test_generic_remediation_is_removed():
    assert create_fixes([
        'Page is missing a title.',
        'Page is missing an H1.',
        'Page is missing a language declaration.',
        'Page is missing a meta description.',
        '1 image(s) are missing alt text.',
    ]) == []


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


def test_fetch_success(monkeypatch):
    monkeypatch.setattr(page, 'urlopen', lambda url: io.BytesIO(b'<html>Hello</html>'))
    assert page.fetch_page('https://example.com/') == '<html>Hello</html>'


@pytest.mark.parametrize(('error', 'message'), [
    (HTTPError('https://example.com/', 404, 'Not Found', {}, None), 'HTTP error: 404'),
    (URLError('offline'), 'Could not reach URL: offline'),
])
def test_fetch_failure(monkeypatch, error, message):
    def fail(url):
        raise error
    monkeypatch.setattr(page, 'urlopen', fail)
    with pytest.raises(RuntimeError, match=message):
        page.fetch_page('https://example.com/')


def test_writer_preserves_json_shape_and_renders_findings(tmp_path):
    run_path = write_results(
        'https://example.com/', ['Example finding'], ['Example fix'], str(tmp_path),
    )
    report = json.loads((run_path / 'report.json').read_text())
    assert report == {
        'url': 'https://example.com/',
        'finding_count': 1, 'fix_count': 1,
        'findings': ['Example finding'], 'fixes': ['Example fix'],
    }
    markdown = (run_path / 'report.md').read_text()
    assert '- Example finding' in markdown
    assert '- Example fix' in markdown


@pytest.mark.parametrize('args', [
    ['scan', 'example.com'], ['https://example.com/docs'],
])
def test_cli_writes_both_reports_without_claiming_a_pass(tmp_path, monkeypatch, capsys, args):
    monkeypatch.chdir(tmp_path)
    requested = []

    def fetch(url):
        requested.append(url)
        return '<html><img src="photo.jpg"></html>'

    monkeypatch.setattr(core, 'fetch_page', fetch)
    assert main(args) == 0
    assert requested == ['https://example.com/']
    report_path, = (tmp_path / 'runs').glob('*/report.json')
    report = json.loads(report_path.read_text())
    assert report['url'] == 'https://example.com/'
    assert report['findings'] == report['fixes'] == []
    assert report['finding_count'] == report['fix_count'] == 0
    markdown = report_path.with_suffix('.md').read_text()
    assert 'no assessment was made' in markdown
    assert 'No issues found' not in markdown
    assert 'No fixes needed' not in markdown
    output = capsys.readouterr().out
    assert 'no assessment was made' in output
    assert 'report.json' in output and 'report.md' in output


def test_cli_fetch_error_is_readable_and_creates_no_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def fail(url):
        raise RuntimeError('Could not reach URL: offline')

    monkeypatch.setattr(core, 'fetch_page', fail)
    assert main(['scan', 'example.com']) == 1
    assert 'Error: Could not reach URL: offline' in capsys.readouterr().err
    assert not (tmp_path / 'runs').exists()


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
