import sys

from legible.analyze.analyzer import analyze_page
from legible.fetch.page import fetch_page
from legible.output.writer import write_findings


def main():
    if len(sys.argv) < 2:
        print("Usage: legible <url>")
        return

    url = sys.argv[1]
    html = fetch_page(url)
    findings = analyze_page(html)

    write_findings(findings)

    print(f"Fetched {len(html)} characters from {url}")
    print(f"Found {len(findings)} issue(s)")
    print("Saved findings to runs/latest/findings.txt")


if __name__ == "__main__":
    main()
