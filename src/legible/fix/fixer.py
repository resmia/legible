from legible.analyze.models import Finding


def create_fixes(findings: list[Finding]) -> list[str]:
    """Keep remediation attached to each failing check."""
    return [finding.fix for finding in findings if finding.fix is not None]


def remediation(check_id: str, state: str) -> str | None:
    if state != 'fail':
        return None
    fixes = {
        'llms-txt': 'Publish a concise llms.txt documentation index and link it from public developer documentation so software can find canonical integration resources.',
        'typed-errors': 'Document stable error codes or structured error response fields and their failure conditions so clients can handle failures predictably.',
        'retry-guidance': 'Document retryable conditions, wait signals or backoff, and safe retry rules so clients can recover from transient failures.',
        'mcp-discovery': 'Publish explicit MCP connection instructions with a server URL or local setup command so clients can discover and connect to the server.',
        'openapi': 'Publish an OpenAPI JSON or YAML specification and link it from the API reference so clients can discover operations and schemas.',
        'auth-mechanism': 'Document the request authentication mechanism, exact header or protocol, and where it applies so developers can construct authenticated requests.',
        'key-issuance': 'Document where developers obtain the required credential, the creation or exchange steps, and any account or approval prerequisites so they can make their first request.',
    }
    return fixes[check_id]
