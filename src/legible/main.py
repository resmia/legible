import sys

from legible.analyze.analyzer import analyze_page
from legible.fetch.page import fetch_page
from legible.fix.fixer import create_fixes
from legible.output.writer import write_results


def main():
    if len(sys.argv) < 2:
        print("Usage: legible <url>")
        return

    url = sys.argv[1]

    html = fetch_page(url)
    findings = analyze_page(html)
    fixes = create_fixes(findings)

    write_results(url, findings, fixes)

    print(f"Fetched {len(html)} characters from {url}")
    print(f"Found {len(findings)} issue(s)")
    print(f"Generated {len(fixes)} fix(es)")
    print("Saved results to runs/latest/")


if __name__ == "__main__":
    main()
    