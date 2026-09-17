from pathlib import Path


def write_results(
    url: str,
    findings: list[str],
    fixes: list[str],
    output_dir: str = "runs/latest",
) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    findings_file = path / "findings.txt"
    fixes_file = path / "fixes.txt"

    findings_lines = [f"URL: {url}", ""]

    if findings:
        findings_lines.extend(findings)
    else:
        findings_lines.append("No issues found.")

    fixes_lines = [f"URL: {url}", ""]

    if fixes:
        fixes_lines.extend(fixes)
    else:
        fixes_lines.append("No fixes needed.")

    findings_file.write_text(
        "\n".join(findings_lines) + "\n",
        encoding="utf-8",
    )

    fixes_file.write_text(
        "\n".join(fixes_lines) + "\n",
        encoding="utf-8",
    )