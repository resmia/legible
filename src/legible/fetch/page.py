from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from legible.fetch.models import FetchObservation


def _observe_response(url: str, response, error: str | None = None) -> FetchObservation:
    final_url = response.geturl()
    status = response.status
    content_type = response.headers.get("Content-Type")
    text = None
    try:
        text = response.read().decode(response.headers.get_content_charset() or "utf-8")
    except (OSError, UnicodeError, LookupError) as exc:
        detail = f"Could not read response: {exc}"
        error = f"{error}; {detail}" if error else detail
    return FetchObservation(url, final_url, status, content_type, text, error)


def fetch_page(url: str) -> FetchObservation:
    """Fetch once, preserving response evidence and expected failures."""
    try:
        with urlopen(url) as response:
            return _observe_response(url, response)
    except HTTPError as exc:
        with exc:
            return _observe_response(url, exc, f"HTTP error: {exc.code}")
    except URLError as exc:
        return FetchObservation(url, error=f"Could not reach URL: {exc.reason}")
    except OSError as exc:
        return FetchObservation(url, error=f"Could not reach URL: {exc}")
