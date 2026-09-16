from urllib.request import urlopen


def fetch_page(url: str) -> str:
    with urlopen(url) as response:
        return response.read().decode("utf-8")
