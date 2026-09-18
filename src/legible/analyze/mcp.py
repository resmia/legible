"""Affirmative MCP provider and connection evidence, without network activity."""
import json
import re
from urllib.parse import urlsplit

MCP = re.compile(r'\bMCP\b|Model Context Protocol', re.I)
CONSUMER = re.compile(r'credential stubs?|injects? credentials|environment variables|third.party|MCP/plugin|tool schemas|repository topics', re.I)
NEGATIVE = re.compile(r'planned|coming soon|not available|no MCP server|example only', re.I)


def http_url(value):
    if not isinstance(value, str) or re.search(r'[<>\s{}]', value):
        return False
    try:
        p = urlsplit(value)
        return p.scheme in {'http', 'https'} and bool(p.hostname) and p.username is None and p.password is None
    except ValueError:
        return False


def mcp_evidence(text, raw=None, url=''):
    """Return (provider excerpt, connection excerpt); mentions alone prove neither."""
    try:
        doc = json.loads(raw or text)
    except (ValueError, TypeError):
        doc = None
    if isinstance(doc, dict):
        transport = doc.get('transport')
        if 'mcp' in url and 'server-card' in url and doc.get('name') and isinstance(transport, dict) and http_url(transport.get('url')):
            return text[:700], text[:700]
        configs = doc.get('mcpServers')
        if isinstance(configs, dict):
            for config in configs.values():
                if isinstance(config, dict) and (http_url(config.get('url')) or
                        config.get('command') and isinstance(config.get('args'), list)):
                    return text[:700], text[:700]
    provider = None
    for match in re.finditer(r'\b(?:MCP|Model Context Protocol) server\b', text, re.I):
        excerpt = text[max(0, match.start()-70):match.end()+350]
        if NEGATIVE.search(excerpt) or CONSUMER.search(excerpt):
            continue
        explicit = re.search(r'\b(?:our|this) (?:MCP|Model Context Protocol) server\b|\b(?:provide|host|offer)s? (?:an? )?(?:MCP|Model Context Protocol) server', excerpt, re.I)
        instructions = re.search(r'\bconnect\b|\bendpoint\b|server URL|client configuration|configure (?:your|the) client|client connection', excerpt, re.I)
        if not (explicit or instructions):
            continue
        provider = excerpt
        urls = re.findall(r'https?://[^\s<>"`]+', excerpt)
        if instructions and any(http_url(u.rstrip('.,;)')) for u in urls):
            return provider, excerpt
        if re.search(r'\b(?:npx|uvx)\s+[\w@./-]+', excerpt) and re.search(r'configure|connect|command|run', excerpt, re.I):
            return provider, excerpt
    if provider:
        # Rendered examples are often embedded inside a prose document, with
        # whitespace around string values introduced by syntax-highlight spans.
        decoder = json.JSONDecoder()
        for start in re.finditer(r'\{', text):
            try:
                value, length = decoder.raw_decode(text[start.start():])
            except ValueError:
                continue
            configs = value.get('mcpServers') if isinstance(value, dict) else None
            if isinstance(configs, dict) and any(isinstance(c, dict) and
                    isinstance(c.get('url'), str) and http_url(c['url'].strip()) for c in configs.values()):
                return provider, text[start.start():start.start()+length]
    return provider, None
