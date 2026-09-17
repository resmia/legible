import argparse
import sys

from legible.core import scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover bounded public surfaces and write a Legible report.",
        epilog="Checks: openapi, auth-mechanism, key-issuance, llms-txt, typed-errors, retry-guidance, mcp-discovery. Legacy legible <url> input is also accepted.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan", help="scan one domain or HTTP(S) URL")
    scan_parser.add_argument("domain")
    web_parser = subparsers.add_parser("web", help="open a local browser report service")
    web_parser.add_argument("--port", type=int, default=8765)
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] not in {"scan", "web"} and not args[0].startswith("-"):
        args.insert(0, "scan")
    parsed = parser.parse_args(args)

    if parsed.command == "web":
        from legible.web import serve
        try:
            serve(parsed.port)
        except (OSError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        run_path = scan(parsed.domain)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Public-surface assessment complete: openapi, auth-mechanism, key-issuance, llms-txt, typed-errors, retry-guidance, mcp-discovery.")
    print(f"Saved JSON report to {run_path / 'report.json'}")
    print(f"Saved Markdown report to {run_path / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
