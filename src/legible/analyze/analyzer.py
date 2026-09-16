def analyze_page(html: str) -> list[str]:
    findings = []

    if "<title>" not in html.lower():
        findings.append("Page is missing a title.")

    return findings
