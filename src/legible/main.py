import argparse
import sys

from legible.core import scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch one homepage and write a Legible scaffold report.",
        epilog="Product checks are not implemented yet. Legacy legible <url> input is also accepted.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan", help="scan one domain or HTTP(S) URL")
    scan_parser.add_argument("domain")
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] != "scan" and not args[0].startswith("-"):
        args.insert(0, "scan")
    parsed = parser.parse_args(args)

    try:
        run_path = scan(parsed.domain)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Homepage fetched. Product checks are not implemented yet; no assessment was made.")
    print(f"Saved JSON report to {run_path / 'report.json'}")
    print(f"Saved Markdown report to {run_path / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
