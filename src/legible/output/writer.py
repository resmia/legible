from pathlib import Path


def write_findings(findings: list[str], output_dir: str = "runs/latest") -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    findings_file = path / "findings.txt"
    findings_file.write_text("\n".join(findings) + "\n", encoding="utf-8")