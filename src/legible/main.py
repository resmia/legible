import sys

from legible.analyze.analyzer import analyze_page
from legible.fetch.page import fetch_page


def main():
    if len(sys.argv) < 2:
        print("Usage: legible <url>")
        return

    url = sys.argv[1]
    html = fetch_page(url)
    findings = analyze_page(html)

    print(f"Fetched {len(html)} characters from {url}")
    print(f"Found {len(findings)} issue(s):")

    for finding in findings:
        print(f"- {finding}")


if __name__ == "__main__":
    main()
    