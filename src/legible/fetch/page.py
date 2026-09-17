from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def fetch_page(url: str) -> str:
    try:
        with urlopen(url) as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP error: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach URL: {exc.reason}") from exc
