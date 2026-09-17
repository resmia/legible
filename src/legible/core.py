"""Single-homepage scan scaffold; discovery and product checks come later."""

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from legible.analyze.analyzer import analyze_page
from legible.fetch.page import fetch_page
from legible.fix.fixer import create_fixes
from legible.output.writer import write_results


def normalize_target(target: str) -> str:
    """Accept a domain or HTTP(S) URL and select its root homepage."""
    target = target.strip()
    if not target or any(character.isspace() for character in target):
        raise ValueError("Provide a domain or an HTTP(S) URL.")
    try:
        parsed = urlsplit(target if "://" in target else f"https://{target}")
        hostname = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError
        hostname = hostname.encode("idna").decode("ascii")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Provide a domain or an HTTP(S) URL without credentials.") from exc
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host}:{port}" if port is not None else host
    return urlunsplit((parsed.scheme, netloc, "/", "", ""))


def scan(target: str, runs_dir: str = "runs") -> Path:
    """Fetch one homepage and preserve the prototype's report format."""
    url = normalize_target(target)
    html = fetch_page(url)
    findings = analyze_page(html)
    fixes = create_fixes(findings)
    return write_results(url, findings, fixes, runs_dir=runs_dir)
