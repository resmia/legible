def create_fixes(findings: list[str]) -> list[str]:
    fixes = []

    for finding in findings:
        if finding == "Page is missing a title.":
            fixes.append(
                "Add a descriptive <title> element inside <head>."
            )

        elif finding == "Page is missing an H1.":
            fixes.append(
                "Add one clear <h1> heading describing the page."
            )

        elif finding == "Page is missing a language declaration.":
            fixes.append(
                'Add a lang attribute to the <html> element, such as <html lang="en">.'
            )

        elif finding == "Page is missing a meta description.":
            fixes.append(
                'Add a descriptive <meta name="description" content="..."> element.'
            )

        elif "image(s) are missing alt text." in finding:
            fixes.append(
                "Add meaningful alt attributes to informative images."
            )

    return fixes
