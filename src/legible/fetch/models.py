from dataclasses import dataclass


@dataclass(frozen=True)
class FetchObservation:
    """One fetch attempt; unavailable response values remain None.

    status is the HTTP status code. error is None on a successful fetch.
    An empty text is an observed empty body; None means no decoded body.
    """

    requested_url: str
    final_url: str | None = None
    status: int | None = None
    content_type: str | None = None
    text: str | None = None
    error: str | None = None
