import sys

from legible.fetch.page import fetch_page


def main():
    if len(sys.argv) < 2:
        print("Usage: legible <url>")
        return

    url = sys.argv[1]
    html = fetch_page(url)

    print(f"Fetched {len(html)} characters from {url}")


if __name__ == "__main__":
    main()