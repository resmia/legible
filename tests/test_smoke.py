from legible.analyze.analyzer import analyze_page


def test_missing_title_is_reported():
    html = "<html><body>No title</body></html>"

    findings = analyze_page(html)

    assert "Page is missing a title." in findings


def test_existing_title_has_no_finding():
    html = "<html><head><title>Hello</title></head></html>"

    findings = analyze_page(html)

    assert findings == []
    