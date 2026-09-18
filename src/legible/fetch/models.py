from dataclasses import dataclass, field
from functools import cached_property


@dataclass(frozen=True)
class RedirectObservation:
    source_url: str
    target_url: str
    status: int


@dataclass(frozen=True)
class FetchMetadata:
    method: str = 'GET'
    redirects: tuple[RedirectObservation, ...] = ()
    encoded_bytes: int = 0
    decoded_bytes: int = 0
    truncated: bool = False
    content_encoding: str = 'identity'


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

    metadata: FetchMetadata | None = field(default=None, compare=False)

    @property
    def canonical_url(self):
        from urllib.parse import urlsplit, urlunsplit
        from legible.fetch.safety import evidence_url
        parsed = urlsplit(evidence_url(self.final_url or self.requested_url))
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', '', ''))

    @cached_property
    def document(self):
        from legible.fetch.document import extract_document
        if self.text is None:
            return None
        return extract_document(self.text, (self.content_type or '').split(';')[0].strip().lower())

    @property
    def availability(self):
        from legible.fetch.document import is_blocked_document
        if self.metadata and self.metadata.method != 'GET':
            return 'body_unavailable'
        if self.metadata and self.metadata.truncated:
            return 'body_truncated'
        if self.error is not None or self.status is None or not 200 <= self.status < 300:
            return 'fetch_rejected_or_failed'
        if not self.text:
            return 'body_unavailable'
        document = self.document
        if document is None:
            return 'unsupported_response'
        if is_blocked_document(document):
            return 'fetch_rejected_or_failed'
        return 'available' if document.text else 'body_unavailable'
