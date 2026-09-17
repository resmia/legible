"""Controlled discovery scaffold; product checks come later."""

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from legible.analyze.analyzer import analyze_page
from legible.analyze.classification import classify_surface
from legible.fetch.page import fetch_page
from legible.discover.surfaces import discover_surfaces
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
    """Discover bounded public resources and retain their observations."""
    url = normalize_target(target)
    observation = fetch_page(url)
    if observation.error is not None:
        raise RuntimeError(observation.error)
    discovery = discover_surfaces(observation, fetch_page)
    findings = analyze_page(observation)
    fixes = create_fixes(findings)
    return write_results(observation, findings, fixes, runs_dir=runs_dir, discovery=discovery,
                         classification=classify_surface(discovery))
