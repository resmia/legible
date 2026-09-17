def create_fixes(findings: list[str]) -> list[str]:
    fixes = []

    for finding in findings:
        if finding == "Page is missing a title.":
            fixes.append("Add a descriptive <title> element inside <head>.")

        if finding == "Page is missing an H1.":
            fixes.append("Add one clear <h1> heading describing the page.")

    return fixes
