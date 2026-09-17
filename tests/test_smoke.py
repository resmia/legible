import json

from legible.analyze.analyzer import analyze_page
from legible.fix.fixer import create_fixes
from legible.output.writer import write_results


def test_bad_page_reports_multiple_structural_problems():
    html = """
    <html>
        <body>
            <img src="photo.jpg">
        </body>
    </html>
    """

    findings = analyze_page(html)

    assert "Page is missing a title." in findings
    assert "Page is missing an H1." in findings
    assert "Page is missing a language declaration." in findings
    assert "Page is missing a meta description." in findings
    assert "1 image(s) are missing alt text." in findings


def test_well_structured_page_has_no_findings():
    html = """
    <html lang="en">
        <head>
            <title>Hello</title>
            <meta name="description" content="Example page">
        </head>
        <body>
            <h1>Welcome</h1>
            <img src="photo.jpg" alt="A mountain">
        </body>
    </html>
    """

    findings = analyze_page(html)

    assert findings == []


def test_fixes_are_created_for_findings():
    findings = [
        "Page is missing a title.",
        "Page is missing a language declaration.",
    ]

    fixes = create_fixes(findings)

    assert len(fixes) == 2
    assert "title" in fixes[0].lower()
    assert "lang" in fixes[1].lower()


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
