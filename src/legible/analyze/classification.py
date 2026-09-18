"""Conservative surface interpretation of existing discovery evidence only."""

from dataclasses import dataclass
import re
from typing import Literal

from legible.analyze.specification import recognize_spec
from legible.analyze.mcp import mcp_evidence
from legible.discover.surfaces import DiscoveryResult, MAX_LINKS, initial_candidates

SurfaceType = Literal['rest', 'mcp', 'sdk', 'cli', 'mixed', 'none', 'unknown']


@dataclass(frozen=True)
class ClassificationEvidence:
    observation_index: int
    source_url: str
    signal: str
    excerpt: str


@dataclass(frozen=True)
class SurfaceClassification:
    kind: SurfaceType
    detected_types: list[str]
    reason: str
    evidence: list[ClassificationEvidence]


HINT = re.compile(r'\b(?:api|rest|openapi|swagger|mcp|sdk|cli|developer|developers|'
                  r'documentation|docs|integration|authentication|oauth|agent setup|'
                  r'command.line|software development kit)\b', re.I)
ENDPOINT = re.compile(r'\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?:https?://[^\s]+/|/)[\w{]')
INSTALL = re.compile(r'\b(?:pip(?:3)? install|npm install|npm i|yarn add|pnpm add|brew install|cargo install|go install)\s+[\w@./-]+', re.I)


def _text(observation):
    return observation.document.text if observation.availability == 'available' else None


def _signals(observation, text):
    if spec := recognize_spec(observation.text):
        yield 'rest', 'api-spec-document', spec
    provider, _ = mcp_evidence(text, observation.text, observation.final_url or observation.requested_url)
    if provider:
        yield 'mcp', 'mcp-documentation', provider
    base = re.search(r'\b(?:REST API|API) base URLs?\s*[:=]?\s*https?://[^\s]+', text, re.I)
    if base and re.search(r'authentication|bearer|API key|GET |POST |API routes', text, re.I):
        yield 'rest', 'rest-documentation', text[max(0, base.start()-30):base.end()+200]
    cli = re.search(r'\b(?:self.hosted CLI|command.line (?:interface|tool)|CLI)\b.{0,200}\b(?:run|install|execute|usage)\b.{0,80}', text, re.I)
    if cli and not re.search(r'planned|coming soon|not supported', cli[0], re.I):
        yield 'cli', 'cli-documentation', cli[0]
    # Keep the two parts close: an unrelated mention elsewhere is insufficient.
    rules = (
        ('rest', r'\b(?:REST(?:ful)? API|API reference|REST documentation)\b',
         re.compile(r'API reference|REST documentation|REST(?:ful)? API (?:reference|documentation)|' + ENDPOINT.pattern, re.I)),
        ('sdk', r'\b(?:SDK|software development kit)\b', INSTALL),
        ('cli', r'\b(?:CLI|command.line (?:interface|tool))\b', INSTALL),
    )
    for kind, label, corroboration in rules:
        for match in re.finditer(label, text, re.I):
            excerpt = text[max(0, match.start() - 120):match.end() + 180]
            if corroboration.search(excerpt):
                # Negative or speculative documentation is not positive evidence.
                if re.search(r'\b(?:no|not|without|unsupported|planned|coming soon)\b', excerpt, re.I):
                    continue
                yield kind, f'{kind}-documentation', excerpt
                break


def classify_surface(discovery: DiscoveryResult) -> SurfaceClassification:
    """No I/O, mutation, product findings, or claims beyond examined resources."""
    evidence = []
    detected = set()
    unresolved = False
    hints = False
    readable_home = False
    for index, observation in enumerate(discovery.observations):
        text = _text(observation)
        source = observation.final_url or observation.requested_url
        if text is None:
            absent = observation.status in {404, 410}
            unresolved |= not absent
            evidence.append(ClassificationEvidence(index, source,
                            'absent' if absent else 'unresolved',
                            f'HTTP {observation.status}; {observation.error or "no readable supported body"}'))
            continue
        if index == 0:
            readable_home = True
        matches = list(_signals(observation, text))
        for kind, signal, excerpt in matches:
            detected.add(kind)
            evidence.append(ClassificationEvidence(index, source, signal, excerpt))
        if not matches:
            hint = HINT.search(text)
            structured = (observation.content_type or "").split(";", 1)[0].strip().lower() in {
                "application/json", "application/yaml", "text/yaml", "application/x-yaml",
            }
            hints |= hint is not None or structured
            evidence.append(ClassificationEvidence(
                index, source, 'ambiguous' if hint or structured else 'examined-no-signal',
                text[max(0, hint.start() - 60):hint.end() + 120] if hint else text[:180],
            ))
    kinds = sorted(detected)
    if kinds:
        return SurfaceClassification('mixed' if len(kinds) > 1 else kinds[0], kinds,
                                     'Types supported by fetched material; coverage is not exhaustive.', evidence)
    # Discovery selection itself can reveal unresolved developer intent.
    hints |= any(s.reason == 'published_link' for s in discovery.surfaces)
    attempted = {o.requested_url for o in discovery.observations}
    attempted.update(o.final_url for o in discovery.observations if o.final_url)
    complete = bool(discovery.observations) and all(
        url in attempted for url, _ in initial_candidates(discovery.observations[0].requested_url)
    )
    capped = sum(s.reason == 'published_link' for s in discovery.surfaces) >= MAX_LINKS
    if readable_home and complete and not unresolved and not hints and not capped:
        return SurfaceClassification('none', [],
            'No software-facing evidence in the bounded examined surface; not a site-wide absence claim.', evidence)
    return SurfaceClassification('unknown', [],
        'Insufficient evidence: coverage is incomplete, material is unreadable, or developer intent is ambiguous.', evidence)
