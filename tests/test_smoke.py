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

import json

from legible.output.writer import write_results


def test_writer_saves_structured_report(tmp_path):
    run_path = write_results(
        "https://example.com",
        ["Page is missing an H1."],
        ["Add one clear <h1> heading describing the page."],
        runs_dir=str(tmp_path),
    )

    report_file = run_path / "report.json"
    report = json.loads(report_file.read_text())

    assert report["url"] == "https://example.com"
    assert report["finding_count"] == 1
    assert report["fix_count"] == 1
    assert report["findings"] == ["Page is missing an H1."]
    assert report["fixes"] == [
        "Add one clear <h1> heading describing the page."
    ]