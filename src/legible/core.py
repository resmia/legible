"""Orchestrate controlled discovery, classification, and public-surface checks."""

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from legible.analyze.analyzer import analyze_surface
from legible.analyze.classification import classify_surface
from legible.fetch.page import fetch_page
from legible.discover.surfaces import discover_surfaces
from legible.fix.fixer import create_fixes
from legible.output.writer import write_results
from legible.models import ScanReport


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


def scan_report(target: str) -> ScanReport:
    """Run the shared pipeline without choosing a presentation or saving files."""
    url = normalize_target(target)
    observation = fetch_page(url)
    def unresolved_checks(discovery):
        findings = analyze_surface(discovery, classify_surface(discovery))
        return frozenset(f.id for f in findings if f.state not in {'pass', 'not_applicable'})

    discovery = discover_surfaces(observation, fetch_page, unresolved_checks=unresolved_checks)
    classification = classify_surface(discovery)
    findings = analyze_surface(discovery, classification)
    fixes = create_fixes(findings)
    return ScanReport(observation, discovery, classification, findings, fixes)


def scan(target: str, runs_dir: str = "runs") -> Path:
    """Preserve the CLI/library entry point and existing report format."""
    report = scan_report(target)
    return write_results(report.homepage, report.findings, report.fixes, runs_dir=runs_dir,
                         discovery=report.discovery, classification=report.classification)
