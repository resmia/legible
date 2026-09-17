"""One fixed probe round and one capped link round; never recursive."""

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
MAX_LINKS = 8
MAX_FETCHES = 1 + len(DOC_HOSTS) + len(PUBLIC_FILES) + MAX_LINKS
RELEVANT = re.compile(
    r"\b(?:api|docs|documentation|developer|developers|authentication|auth|"
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

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.handle_endtag("a")
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.accept(self.href, " ".join(" ".join(self.label).split()))
            self.href = None
            self.label = []


def discover_surfaces(
    homepage: FetchObservation,
    fetch: Callable[[str], FetchObservation],
) -> DiscoveryResult:
    """Reuse the homepage, retain failed probes, and fetch at most eight links.

    Only initial successful HTML supplies links. Exact initial origins and their
    observed redirect origins are allowed; arbitrary external hosts are deferred.
    Redirect hops remain governed by the existing shared fetch layer.
    """
    result = DiscoveryResult()
    seen: set[str] = set()

    def add(observation, reason, source=None, label=None):
        result.surfaces.append(DiscoveredSurface(
            observation.requested_url, reason, source, label, len(result.observations),
        ))
        result.observations.append(observation)
        for url in (observation.requested_url, observation.final_url):
            normalized = _public_url(url) if url else None
            if normalized:
                seen.add(normalized)

    add(homepage, "homepage")
    candidates = initial_candidates(homepage.requested_url)
    allowed = {_origin(_public_url(url) or url) for url, _ in candidates}
    for url, reason in candidates[1:]:
        if _public_url(url) not in seen:
            add(fetch(url), reason)
    seeds = list(result.observations)
    for observation in seeds:
        final = _public_url(observation.final_url) if observation.final_url else None
        if final:
            allowed.add(_origin(final))

    links: list[tuple[str, str, str]] = []
    for observation in seeds:
        media_type = (observation.content_type or "").split(";", 1)[0].strip().lower()
        if (observation.error is not None or observation.status is None
                or not 200 <= observation.status < 300
                or media_type not in {"text/html", "application/xhtml+xml"}
                or not observation.text):
            continue
        source = observation.final_url or observation.requested_url

        def accept(href, label):
            if len(links) >= MAX_LINKS or not href or href.startswith("#"):
                return
            try:
                url = _public_url(urljoin(source, href))
            except ValueError:
                return
            if (url is None or url in seen or _origin(url) not in allowed
                    or not RELEVANT.search(f"{urlsplit(url).path} {label}")):
                return
            seen.add(url)
            links.append((url, source, label))

        parser = _Links(accept)
        parser.feed(observation.text)
        parser.close()
        parser.handle_endtag("a")
        if len(links) == MAX_LINKS:
            break
    for url, source, label in links:
        # A preceding linked fetch may redirect to another selected resource.
        if any(_public_url(item.final_url) == url for item in result.observations if item.final_url):
            continue
        add(fetch(url), "published_link", source, label)
    return result
