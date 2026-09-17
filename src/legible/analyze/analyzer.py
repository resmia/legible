def analyze_page(html: str) -> list[str]:
    """Analysis extension point; v1 software-surface checks are not implemented.

    An empty result means no checks ran, not that this page passed an assessment.
    """
    return []
