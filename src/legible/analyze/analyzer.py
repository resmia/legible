from legible.analyze.rules import inspect_page


def analyze_page(html: str) -> list[str]:
    signals = inspect_page(html)
    findings = []

    if not signals.has_title:
        findings.append("Page is missing a title.")

    if signals.h1_count == 0:
        findings.append("Page is missing an H1.")

    if not signals.has_language:
        findings.append("Page is missing a language declaration.")

    if not signals.has_meta_description:
        findings.append("Page is missing a meta description.")

    if signals.images_missing_alt > 0:
        findings.append(
            f"{signals.images_missing_alt} image(s) are missing alt text."
        )

    return findings
