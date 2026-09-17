"""Priority discovery with fixed navigation depth and a hard fetch ceiling."""

from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from ipaddress import ip_address
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from legible.fetch.models import FetchObservation

DOC_HOSTS = ("docs", "api", "developer", "developers")
PUBLIC_FILES = (
    "/llms.txt", "/openapi.json", "/openapi.yaml", "/swagger.json",
    "/.well-known/mcp-server-card", "/.well-known/mcp/server-card.json",
)
MAX_LINKS = 29
MAX_FETCHES = 30
MAX_NAVIGATION_DEPTH = 3
RELEVANT = re.compile(
    r"\b(?:api|docs|documentation|developer|developers|authentication|auth|credentials?|llms|reference|index[.](?:md|txt)|"
    r"errors?|rate[\s_-]*limits?|retr(?:y|ies)|mcp|agent[\s_-]*setup|openapi|swagger)\b",
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


class _Links(HTMLParser):
    def __init__(self, accept: Callable[[str, str], None]):
        super().__init__(convert_charrefs=True)
        self.accept = accept
        self.href: str | None = None
        self.label: list[str] = []
        self.visible: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'template'}:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "a":
            self.handle_endtag("a")
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data):
        if self.hidden:
            return
        self.visible.append(data)
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'template'} and self.hidden:
            self.hidden -= 1
        if tag == "a" and self.href is not None:
            self.accept(self.href, " ".join(" ".join(self.label).split()))
            self.href = None
            self.label = []


def _priority(url, label):
    value = f"{urlsplit(url).path} {label}"
    for priority, pattern in enumerate((
        r"llms|openapi|swagger|index\.(?:md|txt|json)",
        r"auth|credential|api[ -]?keys?",
        r"api|reference|errors?|rate[ _-]?limits?|retry|mcp|agent[ _-]?setup",
    )):
        if re.search(pattern, value, re.I):
            return priority
    return 3


def discover_surfaces(homepage: FetchObservation,
                      fetch: Callable[[str], FetchObservation],
                      sufficient: Callable[[DiscoveryResult], bool] | None = None) -> DiscoveryResult:
    """Expand seeds, one docs-entry layer, and one index layer; never crawl leaves.

    Published pointers preempt guesses. Origins remain restricted to fixed seeds
    and their redirects. A finite queue and depth cap bound follow-up work.
    """
    result = DiscoveryResult()
    candidates = initial_candidates(homepage.requested_url)
    allowed = {_origin(url) for url, _ in candidates}
    seen = set()
    pending = {}
    sequence = 0

    def enqueue(url, reason, source=None, label=None, depth=0):
        nonlocal sequence
        if url in seen:
            return
        priority = _priority(url, label or '') if reason == 'published_link' else 4
        entry = (priority, sequence, url, reason, source, label, depth)
        if url not in pending or priority < pending[url][0]:
            pending[url] = entry
            sequence += 1

    def add(observation, reason, source=None, label=None, depth=0):
        result.surfaces.append(DiscoveredSurface(
            observation.requested_url, reason, source, label, len(result.observations)))
        result.observations.append(observation)
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
        path = urlsplit(source).path
        index = bool(re.search(r'(?:llms(?:-full)?|index)\.(?:txt|md)$', path, re.I))
        entry = path == '/' or bool(re.fullmatch(r'/(?:docs|documentation|developers?|reference|api)/?', path))
        # Only named navigation surfaces expand beyond the initial seeds.
        if depth >= MAX_NAVIGATION_DEPTH or (depth and not (index or (depth == 1 and entry))):
            return

        def accept(href, label):
            if not href or href.startswith('#'):
                return
            try:
                url = _public_url(urljoin(source, href))
            except ValueError:
                return
            if (url and _origin(url) in allowed
                    and RELEVANT.search(f'{urlsplit(url).path} {label}')):
                enqueue(url, 'published_link', source, label, depth + 1)

        if media in {'text/html', 'application/xhtml+xml'}:
            parser = _Links(accept)
            parser.feed(observation.text)
            parser.close()
            parser.handle_endtag('a')
        elif media in {'text/plain', 'text/markdown'}:
            for match in re.finditer(r'\[([^]\n]+)\]\(([^)\s]+)\)', observation.text):
                accept(match[2], match[1])
        # Publishers also advertise indexes as literal paths in visible prose.
        if media in {'text/html', 'application/xhtml+xml', 'text/plain', 'text/markdown'}:
            visible = ' '.join(parser.visible) if media in {'text/html', 'application/xhtml+xml'} else observation.text
            for match in re.finditer(r'(?:https?://[^\s<>"`]+)?/[\w./-]*llms(?:-full)?\.txt',
                                     visible):
                accept(match[0], 'Published machine-readable index')

    for url, reason in candidates[1:]:
        enqueue(url, reason)
    add(homepage, 'homepage')
    while pending and len(result.observations) < MAX_FETCHES:
        # Once published evidence settles all implemented checks, skip guesses.
        if (sufficient and all(item[3] != 'published_link' for item in pending.values())
                and sufficient(result)):
            break
        item = min(pending.values())
        _, _, url, reason, source, label, depth = item
        pending.pop(url)
        if url not in seen:
            add(fetch(url), reason, source, label, depth)
    result.pending_urls = sorted(pending)
    return result
