from legible.fetch.models import FetchObservation


def analyze_page(observation: FetchObservation) -> list[str]:
    """Analysis extension point; v1 software-surface checks are not implemented.

    An empty result means no checks ran, not that this page passed an assessment.
    """
    return []
