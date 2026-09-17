from legible.analyze.models import Finding


def create_fixes(findings: list[Finding]) -> list[str]:
    """Keep remediation attached to each failing or unresolved check."""
    return [finding.fix for finding in findings if finding.fix is not None]


def remediation(check_id: str, state: str) -> str | None:
    if state not in {'fail', 'unknown'}:
        return None
    fixes = {
        'openapi': 'Publish an OpenAPI JSON or YAML specification and link it from the API reference so clients can discover operations and schemas.',
        'auth-mechanism': 'Document the request authentication mechanism, exact header or protocol, and where it applies so developers can construct authenticated requests.',
        'key-issuance': 'Document where developers obtain the required credential, the creation or exchange steps, and any account or approval prerequisites so they can make their first request.',
    }
    prefix = 'Make the relevant public documentation accessible and clarify the evidence. ' if state == 'unknown' else ''
    return prefix + fixes[check_id]
