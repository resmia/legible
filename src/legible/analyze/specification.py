"""Shared structural recognition, without OpenAPI schema validation."""
import json
import re

import yaml


def recognize_spec(raw: str) -> str | None:
    """Parse one document safely; require a version and both root mappings."""
    try:
        document = json.loads(raw)
    except (ValueError, TypeError):
        try:
            document = yaml.safe_load(raw)
        except (yaml.YAMLError, ValueError, RecursionError):
            return None
    if not isinstance(document, dict):
        return None
    version = document.get('openapi', document.get('swagger'))
    # YAML treats an unquoted Swagger 2.0 scalar as numeric.
    if 'openapi' not in document and version == 2.0:
        version = '2.0'
    if (isinstance(version, str)
            and re.fullmatch(r'3\.\d+\.\d+' if 'openapi' in document else r'2\.0', version)
            and isinstance(document.get('info'), dict)
            and isinstance(document.get('paths'), dict)):
        return f'version={version}; info and paths mappings present (not schema validation)'
    return None
