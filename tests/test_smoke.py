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
