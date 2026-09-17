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

    try:
        html = fetch_page(url)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return

    findings = analyze_page(html)
    fixes = create_fixes(findings)

    run_path = write_results(url, findings, fixes)

    print(f"Fetched {len(html)} characters from {url}")
    print(f"Found {len(findings)} issue(s)")
    print(f"Generated {len(fixes)} fix(es)")
    print(f"Saved report to {run_path / 'report.json'}")


if __name__ == "__main__":
    main()
