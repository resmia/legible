"""Small, ranked views of retained evidence; never changes engine determinations."""
from dataclasses import replace
import re
from urllib.parse import urlsplit

from legible.analyze.specification import recognize_spec
from legible.analyze.remaining import _structured

EXCERPT_LIMIT = 420
TOPICS = {
    'openapi': r'openapi|swagger|specification',
    'llms-txt': r'llms(?:-full)?\.txt|machine.readable.*index|index\.(?:md|txt)',
    'auth-mechanism': r'auth|bearer|api[ -]key|oauth|securitySchemes',
    'key-issuance': r'credential|api[ -]key|token|dashboard|settings',
    'typed-errors': r'error|failure',
    'retry-guidance': r'retry|retries|backoff|429|rate.limit|idempotenc',
    'mcp-discovery': r'mcp|model context protocol',
}
DIRECT = {
    'openapi': r'openapi|swagger',
    'llms-txt': r'\[[^]]+\]\([^)]*\)',
    'auth-mechanism': r'Authorization|Bearer|API[ -]key|OAuth|HTTP Basic|securitySchemes',
    'key-issuance': r'(?:create|generate|obtain|get|copy|exchange|find|view|retrieve)\b.{0,100}(?:key|token|credential)|(?:key|token).{0,100}(?:dashboard|settings|console|endpoint)',
    'typed-errors': r'structured error fields|error (?:object|response|code|type)|error_code',
    'retry-guidance': r'Retry-After|exponential.{0,30}backoff|retry.{0,80}(?:429|503|transient)|idempotenc.{0,80}(?:retry|retries)',
    'mcp-discovery': r'mcpServers|transport|(?:endpoint|connect|server URL).{0,100}https?://|\b(?:npx|uvx)\b',
}


def concise_excerpt(text, pattern):
    text = ' '.join(text.split())
    match = re.search(pattern, text, re.I)
    start = max(0, match.start() - 70) if match else 0
    prefix = '… ' if start else ''
    room = EXCERPT_LIMIT - len(prefix)
    excerpt = text[start:start + room]
    if start + room < len(text):
        excerpt = excerpt[:room-1].rsplit(' ', 1)[0] + '…'
    return prefix + excerpt


def select_evidence(finding, report):
    """Prefer direct evidence; uncertainty uses relevant attempts, not all sources."""
    if finding.state == 'not_applicable':
        return []
    topic, direct = TOPICS[finding.id], DIRECT[finding.id]
    ranked = []
    for item in finding.evidence:
        surface = next((s for s in report.discovery.surfaces
                        if s.observation_index == item.observation_index), None)
        location = urlsplit(item.source_url).path
        label = f'{location} {surface.link_text or ""}' if surface else location
        relevant_location = bool(re.search(topic, label, re.I))
        relevant_text = bool(re.search(topic, item.excerpt, re.I))
        if not (relevant_location or relevant_text):
            continue
        readable = item.error is None and item.status is not None and 200 <= item.status < 300
        strength = 1 + int(relevant_location)
        if readable and relevant_text and re.search(direct, item.excerpt, re.I):
            strength = 4 + int(relevant_location)
        observation = report.discovery.observations[item.observation_index]
        if readable and finding.id == 'openapi' and recognize_spec(observation.text):
            strength = 8
        if readable and finding.id == 'typed-errors' and (
                'structured error fields' in item.excerpt or _structured(item.excerpt)):
            strength = 7
        if readable and finding.id == 'llms-txt' and re.search(r'/llms(?:-full)?\.txt$', location):
            strength = 8
        if readable and finding.id == 'mcp-discovery' and 'json' in (item.content_type or '') and re.search(direct, item.excerpt, re.I):
            strength = 8
        if finding.state == 'unknown' and not readable and relevant_location:
            strength = 6
        ranked.append((strength, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].observation_index))
    # One direct artifact often suffices; retain peers, not weaker filler pages.
    threshold = ranked[0][0] if ranked and ranked[0][0] >= 4 else 1
    selected, seen = [], set()
    for strength, item in ranked:
        if strength < threshold or item.source_url in seen:
            continue
        selected.append(replace(item, excerpt=concise_excerpt(item.excerpt, direct)))
        seen.add(item.source_url)
        if len(selected) == (3 if finding.state == 'unknown' else 2):
            break
    return selected
