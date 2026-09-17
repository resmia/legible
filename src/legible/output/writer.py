import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from legible.analyze.classification import SurfaceClassification
from legible.fetch.models import FetchObservation
from legible.discover.surfaces import DiscoveryResult, MAX_FETCHES, MAX_LINKS


def _make_run_name(url: str) -> str:
    hostname = urlparse(url).hostname or "unknown"
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return f"{timestamp}-{hostname}"


def _make_markdown_report(
    observation: FetchObservation,
    findings: list[str],
    fixes: list[str],
    discovery: DiscoveryResult | None = None,
    classification: SurfaceClassification | None = None,
) -> str:
    lines = [
        "# Legible Report",
        "",
        f"URL: {observation.requested_url}",
        "",
        "Product checks are not implemented yet; no assessment was made.",
        "",
        f"Findings: {len(findings)}",
        f"Fixes: {len(fixes)}",
        "",
    ]

    if classification:
        section = ["## Surface classification", "", f"Surface: {classification.kind}",
                   classification.reason, ""]
        for item in classification.evidence:
            section.append(f"- Observation {item.observation_index}: {item.source_url} — "
                           f"{item.signal}: {item.excerpt}")
        section.append("")
        lines.extend(section)

    lines.extend(["## Findings", ""])
    if findings:
        for finding in findings:
            lines.append(f"- {finding}")
    else:
        lines.append("No findings generated.")

    lines.extend([
        "",
        "## Suggested Fixes",
        "",
    ])

    if fixes:
        for fix in fixes:
            lines.append(f"- {fix}")
    else:
        lines.append("No fixes generated.")

    lines.extend(["", "## Sources examined", ""])
    observations = discovery.observations if discovery else [observation]
    if discovery:
        lines.extend([
            f"Discovery caps: {MAX_FETCHES} fetches, including at most {MAX_LINKS} published links.",
            "Candidates are not validated capabilities. Linked pages are not crawled.", "",
        ])
    for index, source in enumerate(observations):
        lines.extend([
            f"- Requested URL: {source.requested_url}",
            f"- Source URL: {source.final_url or source.requested_url}",
            f"- HTTP status: {source.status if source.status is not None else 'unavailable'}",
            f"- Content type: {source.content_type or 'unavailable'}",
            f"- Fetch error: {source.error or 'none'}",
        ])
        if discovery:
            surface = discovery.surfaces[index]
            lines.append(f"- Discovery reason: {surface.reason}")
            if surface.source_url:
                lines.append(f"- Linked from: {surface.source_url}")
        lines.append("")

    return "\n".join(lines) + "\n"


def write_results(
    observation: FetchObservation,
    findings: list[str],
    fixes: list[str],
    runs_dir: str = "runs",
    *,
    discovery: DiscoveryResult | None = None,
    classification: SurfaceClassification | None = None,
) -> Path:
    run_name = _make_run_name(observation.requested_url)
    run_path = Path(runs_dir) / run_name
    run_path.mkdir(parents=True, exist_ok=True)

    report = {
        "url": observation.requested_url,
        "observations": [asdict(item) for item in (discovery.observations if discovery else [observation])],
        "finding_count": len(findings),
        "fix_count": len(fixes),
        "findings": findings,
        "fixes": fixes,
    }

    if classification:
        report["classification"] = asdict(classification)

    if discovery:
        report["discovery"] = {
            "max_fetches": MAX_FETCHES,
            "max_linked_fetches": MAX_LINKS,
            "surfaces": [asdict(surface) for surface in discovery.surfaces],
        }

    json_file = run_path / "report.json"
    markdown_file = run_path / "report.md"

    json_file.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    markdown_file.write_text(
        _make_markdown_report(observation, findings, fixes, discovery, classification),
        encoding="utf-8",
    )

    return run_path
