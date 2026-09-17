from pathlib import Path
from legible.analyze.analyzer import analyze_page


def test_missing_title_and_h1_are_reported():
    html = "<html><body>No title or heading</body></html>"

    findings = analyze_page(html)

    assert "Page is missing a title." in findings
    assert "Page is missing an H1." in findings


def test_page_with_title_and_h1_has_no_findings():
    html = "<html><head><title>Hello</title></head><body><h1>Welcome</h1></body></html>"

    findings = analyze_page(html)

    assert findings == []

from legible.output.writer import write_results


def test_writer_saves_url_findings_and_fixes(tmp_path):
    output_dir = tmp_path / "run"

    write_results(
        "https://example.com",
        ["Page is missing an H1."],
        ["Add one clear <h1> heading describing the page."],
        output_dir=str(output_dir),
    )

    findings_contents = (output_dir / "findings.txt").read_text()
    fixes_contents = (output_dir / "fixes.txt").read_text()

    assert "URL: https://example.com" in findings_contents
    assert "Page is missing an H1." in findings_contents
    assert "Add one clear <h1> heading describing the page." in fixes_contents