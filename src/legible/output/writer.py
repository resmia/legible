import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from legible.fetch.models import FetchObservation


def _make_run_name(url: str) -> str:
    hostname = urlparse(url).hostname or "unknown"
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return f"{timestamp}-{hostname}"


def _make_markdown_report(
    observation: FetchObservation,
    findings: list[str],
    fixes: list[str],
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
        "## Findings",
        "",
    ]

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

    lines.extend([
        "",
        "## Sources examined",
        "",
        f"- Requested URL: {observation.requested_url}",
        f"- Source URL: {observation.final_url or observation.requested_url}",
        f"- HTTP status: {observation.status if observation.status is not None else 'unavailable'}",
        f"- Content type: {observation.content_type or 'unavailable'}",
        f"- Fetch error: {observation.error or 'none'}",
    ])

    return "\n".join(lines) + "\n"


def write_results(
    observation: FetchObservation,
    findings: list[str],
    fixes: list[str],
    runs_dir: str = "runs",
) -> Path:
    run_name = _make_run_name(observation.requested_url)
    run_path = Path(runs_dir) / run_name
    run_path.mkdir(parents=True, exist_ok=True)

    report = {
        "url": observation.requested_url,
        "observations": [asdict(observation)],
        "finding_count": len(findings),
        "fix_count": len(fixes),
        "findings": findings,
        "fixes": fixes,
    }

    json_file = run_path / "report.json"
    markdown_file = run_path / "report.md"

    json_file.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    markdown_file.write_text(
        _make_markdown_report(observation, findings, fixes),
        encoding="utf-8",
    )

    return run_path
