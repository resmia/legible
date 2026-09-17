import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def _make_run_name(url: str) -> str:
    hostname = urlparse(url).hostname or "unknown"
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return f"{timestamp}-{hostname}"


def write_results(
    url: str,
    findings: list[str],
    fixes: list[str],
    runs_dir: str = "runs",
) -> Path:
    run_name = _make_run_name(url)
    run_path = Path(runs_dir) / run_name
    run_path.mkdir(parents=True, exist_ok=True)

    report = {
        "url": url,
        "finding_count": len(findings),
        "fix_count": len(fixes),
        "findings": findings,
        "fixes": fixes,
    }

    report_file = run_path / "report.json"

    report_file.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )

    return run_path