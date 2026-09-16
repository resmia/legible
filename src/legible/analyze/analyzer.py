def analyze_page(html: str) -> list[str]:
    findings = []

    html_lower = html.lower()

    if "<title>" not in html_lower:
        findings.append("Page is missing a title.")

    if "<h1" not in html_lower:
        findings.append("Page is missing an H1.")

    return findings
