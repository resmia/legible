"""Priority discovery with fixed navigation depth and a hard fetch ceiling."""

from collections.abc import Callable
from dataclasses import dataclass, field
from ipaddress import ip_address
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from legible.fetch.models import FetchObservation
from legible.fetch.safety import validate_public_url, related_host, UnsafeURL
from legible.discover.links import published_links
from legible.discover.artifacts import ArtifactChain

DOC_HOSTS = ("docs", "api", "developer", "developers")
PUBLIC_FILES = (
    "/llms.txt", "/openapi.json", "/openapi.yaml", "/swagger.json",
    "/.well-known/mcp-server-card", "/.well-known/mcp/server-card.json",
)
MAX_LINKS = 29
MAX_FETCHES = 30
MAX_NAVIGATION_DEPTH = 3
MAX_RELATED_ORIGINS = 3
MAX_EXTERNAL_ARTIFACTS = 2
RELEVANT = re.compile(
    r"\b(?:api|docs|documentation|developer|developers|authentication|auth|credentials?|keys?|tokens?|oauth|bearer|authorization|secrets?|settings|getting[ _-]?started|llms|reference|index[.](?:md|txt)|"
    r"changelog|development|quickstart|integration|specification|cli|command[ -]line|sdk|model context protocol|errors?|backoff|idempotency|429|schema|rate[\s_-]*limits?|retr(?:y|ies)|mcp|agent[\s_-]*setup|openapi|swagger)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DiscoveredSurface:
    """Fetch intent and provenance, not a validated surface classification."""

    url: str
    reason: str
    source_url: str | None
    link_text: str | None
    observation_index: int


@dataclass
class DiscoveryResult:
    observations: list[FetchObservation] = field(default_factory=list)
    surfaces: list[DiscoveredSurface] = field(default_factory=list)
    pending_urls: list[str] = field(default_factory=list)


def _public_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or any(c.isspace() for c in url)):
            return None
        host = parsed.hostname.encode("idna").decode("ascii")
        host = f"[{host}]" if ":" in host else host
        port = parsed.port
        if port is not None and (parsed.scheme, port) not in {("http", 80), ("https", 443)}:
            host = f"{host}:{port}"
        return urlunsplit((parsed.scheme, host, parsed.path or "/", "", ""))
    except (ValueError, UnicodeError):
        return None


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def initial_candidates(homepage: str) -> list[tuple[str, str]]:
    parsed = urlsplit(homepage)
    host = parsed.hostname
    candidates = [(homepage, "homepage")]
    try:
        ip_address(host)
        guess_hosts = False
    except ValueError:
        guess_hosts = "." in host
    if guess_hosts:
        # Strip only the conventional www prefix; do not guess registrable domains.
        domain = host.removeprefix("www.")
        for prefix in DOC_HOSTS:
            netloc = f"{prefix}.{domain}"
            if parsed.port is not None:
                netloc += f":{parsed.port}"
            candidates.append((urlunsplit((parsed.scheme, netloc, "/", "", "")), "likely_host"))
    candidates.extend((urljoin(homepage, path), "public_file") for path in PUBLIC_FILES)
    return candidates


IMPLEMENTED_CHECKS = frozenset({'openapi', 'auth-mechanism', 'key-issuance', 'llms-txt', 'typed-errors', 'retry-guidance', 'mcp-discovery'})


def _priority(url, label, reason, unresolved):
    """Rank navigation separately from evidence for still-unresolved checks."""
    if reason == 'public_file':
        return 2
    if reason == 'likely_host':
        return 5
    path = urlsplit(url).path
    direct = re.sub(r'[-_/]', ' ', f'{path} {label.split(" — ", 1)[0]}').lower()
    value = re.sub(r'[-_/]', ' ', f'{path} {label}').lower()
    if 'openapi' in unresolved and re.search(r'openapi|swagger|api specification', value):
        return -3
    if 'retry-guidance' in unresolved and re.search(r'safe to retry|retryable|backoff|retry|retries|rate.limit|idempotenc', value):
        return -2
    if 'typed-errors' in unresolved and re.search(r'error|failure|error schema', value):
        return -1
    if re.search(r'llms|openapi|swagger|index\.(?:md|txt|json)|\bmcp\b|model context protocol|\bcli\b|command.line|\bsdk\b|developer resources|developer docs|\bdevelopment\b', direct):
        return 0
    consumer = bool(re.search(r'\buser\b|customer|consumer|identity|verification|\bmfa\b|\b2fa\b|fraud|ebook|marketing', value))
    if not consumer:
        if 'key-issuance' in unresolved and re.search(r'api keys?|credential|dashboard|settings|token endpoint', value):
            return 0.5
        if 'auth-mechanism' in unresolved and re.search(r'auth|bearer|oauth|api keys?|credential', value):
            return 1 if re.search(r'api|request|bearer|credential|oauth', value) else 1.5
    if 'openapi' in unresolved and re.search(r'changelog|api version', direct):
        # A published text index precedes individual release navigation.
        return 1.7 if re.search(r'/(?:changelog|versions?)\.md$', path) else 1.75
    if (re.fullmatch(r'/(?:docs|documentation|developers?|reference|api)/?', path)
            or re.fullmatch(r'(?:api reference|developer documentation|documentation|docs)', label, re.I)):
        return 0
    return 6


def discover_surfaces(homepage: FetchObservation,
                      fetch: Callable[[str], FetchObservation],
                      unresolved_checks: Callable[[DiscoveryResult], frozenset[str]] | None = None) -> DiscoveryResult:
    """Re-rank published integration trails after each fetch; cap depth and origins."""
    result = DiscoveryResult()
    candidates = initial_candidates(homepage.requested_url)
    allowed = {_origin(url) for url, _ in candidates}
    seen = set()
    pending = {}
    sequence = 0
    related = set()
    external = set()
    root_host = urlsplit(homepage.requested_url).hostname
    external_urls = set()
    checked_origins = {}
    artifact_chain = None

    def enqueue(url, reason, source=None, label=None, depth=0):
        nonlocal sequence
        if url in seen:
            return
        priority = _priority(url, label or '', reason, IMPLEMENTED_CHECKS)
        entry = (priority, sequence, url, reason, source, label, depth)
        if (url not in pending or priority < pending[url][0]
                or (reason == 'published_link' and pending[url][3] != 'published_link')):
            pending[url] = entry
            sequence += 1

    def add(observation, reason, source=None, label=None, depth=0):
        nonlocal artifact_chain
        result.surfaces.append(DiscoveredSurface(
            observation.requested_url, reason, source, label, len(result.observations)))
        result.observations.append(observation)
        if observation.metadata and observation.metadata.method != 'GET':
            # A probe is retained for provenance, never treated as content fetched.
            enqueue(observation.requested_url, reason, source, label, depth)
            return
        for value in (observation.requested_url, observation.final_url):
            url = _public_url(value) if value else None
            if url:
                seen.add(url)
                pending.pop(url, None)
                if reason != 'published_link' or observation.requested_url in {u for u, _ in candidates}:
                    allowed.add(_origin(url))
        media = (observation.content_type or '').split(';')[0].strip().lower()
        if (observation.error or observation.status is None
                or not 200 <= observation.status < 300 or not observation.text):
            return
        source = observation.final_url or observation.requested_url
        if observation.requested_url in external_urls:
            if artifact_chain and observation.requested_url in artifact_chain.steps:
                unresolved = unresolved_checks(result) if unresolved_checks else IMPLEMENTED_CHECKS
                if 'openapi' in unresolved:
                    next_step = artifact_chain.follow(observation, _public_url)
                    if next_step:
                        url, title = next_step
                        try:
                            validate_public_url(url)
                        except (UnsafeURL, OSError, ValueError):
                            return
                        external_urls.add(url)
                        enqueue(url, 'published_link', source,
                                'Bounded OpenAPI artifact step: ' + title, depth + 1)
            return
        # Every readable official resource can emit ranked candidates, within depth.
        # External artifacts are leaves, not new crawl roots.
        links = published_links(observation.text, media)
        def link_rank(link):
            try:
                return _priority(urljoin(source, link.href), link.label + ' ' + link.context, 'published_link', IMPLEMENTED_CHECKS)
            except ValueError:
                return 99
        links.sort(key=link_rank)
        for link in links:
            if not link.href or link.href.startswith('#'):
                continue
            try:
                url = _public_url(urljoin(source, link.href))
            except ValueError:
                continue
            if not url:
                continue
            # Base URLs describe a surface; do not execute published API paths.
            if link.label == 'Published integration location' and re.search(r'API base URL', link.context, re.I):
                url = _origin(url)
            if url in seen:
                continue
            meaning = link.label + (' ' + link.context if not link.navigation else '')
            if not RELEVANT.search(f'{urlsplit(url).path} {meaning}'):
                continue
            origin = _origin(url)
            # At the navigation boundary permit one explicit formal-spec publication
            # page, then only its external artifact. Ordinary crawling still stops.
            if depth >= MAX_NAVIGATION_DEPTH and not (
                    (depth == MAX_NAVIGATION_DEPTH or
                     depth == MAX_NAVIGATION_DEPTH + 1 and origin not in allowed)
                    and re.search(r'openapi|swagger|API specification|API schema', meaning, re.I)):
                continue
            admission = ''
            if origin not in allowed:
                host = urlsplit(url).hostname
                is_related = related_host(host, root_host)
                # An explicit publisher pointer grants a bounded delegation, not
                # inferred ownership. Deceptive suffixes cannot use related capacity.
                if root_host.removeprefix('www.') + '.' in host and not is_related:
                    continue
                strong = re.search(r'openapi|swagger|specification|schema|canonical|machine.readable|documentation|docs|official.*(?:source|repository)|sdk',
                                   f'{urlsplit(url).path} {meaning}', re.I)
                if not strong:
                    continue
                if not is_related:
                    artifact = re.search(r'openapi|swagger|API specification|API schema|official.*(?:source|repository|SDK)|canonical.*(?:docs|documentation|contract)',
                                         f'{urlsplit(url).path} {link.label}', re.I)
                    delegated_docs = depth == 0 and re.search(r'\bdocs\b|documentation|developer', link.label, re.I)
                    if not (artifact or delegated_docs):
                        continue
                if is_related:
                    if origin not in related and len(related) >= MAX_RELATED_ORIGINS:
                        continue
                elif url not in external and len(external) >= MAX_EXTERNAL_ARTIFACTS:
                    continue
                if origin not in checked_origins:
                    if len(checked_origins) >= MAX_RELATED_ORIGINS + MAX_EXTERNAL_ARTIFACTS + 3:
                        continue
                    try:
                        validate_public_url(url)
                        checked_origins[origin] = True
                    except (UnsafeURL, OSError, ValueError):
                        checked_origins[origin] = False
                if not checked_origins[origin]:
                    continue
                if is_related:
                    related.add(origin)
                    allowed.add(origin)
                    admission = 'Explicit related-origin documentation: '
                else:
                    external.add(url)
                    external_urls.add(url)
                    admission = 'Explicit one-hop external artifact: '
                    if artifact_chain is None and re.search(r'openapi|swagger|API specification|API schema|API contract',
                                                           f'{urlsplit(url).path} {meaning}', re.I):
                        artifact_chain = ArtifactChain(url)
            if origin in related and not admission:
                admission = 'Explicit related-origin documentation: '
            # Keep original labels plus publisher context in existing provenance fields.
            label = admission + link.label
            if not link.navigation and link.context.strip() and link.context.strip() != link.label.strip():
                label += ' — ' + link.context.strip()
            enqueue(url, 'published_link', source, label, depth + 1)

    for url, reason in candidates[1:]:
        enqueue(url, reason)
    add(homepage, 'homepage')
    while pending and len(result.observations) < MAX_FETCHES:
        # Core evaluates pure checks against the current evidence and pending work.
        result.pending_urls = sorted(pending)
        unresolved = unresolved_checks(result) if unresolved_checks else IMPLEMENTED_CHECKS
        def rank(item):
            _, order, url, reason, _, label, _ = item
            return (_priority(url, label or '', reason, unresolved), item[6], order)
        item = min(pending.values(), key=rank)
        # Explicit entry/index/spec/MCP pointers can reveal another surface even
        # after positive findings. Lower-priority work needs an unresolved check.
        if not unresolved and rank(item)[0] > 0:
            break
        _, _, url, reason, source, label, depth = item
        pending.pop(url)
        if url not in seen:
            add(fetch(url), reason, source, label, depth)
    result.pending_urls = sorted(pending)
    return result
