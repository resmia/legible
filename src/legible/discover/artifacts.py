"""One explicitly delegated specification trail; no repository-wide traversal."""
from dataclasses import dataclass, field
import re
from urllib.parse import unquote, urlsplit, urljoin

from legible.analyze.specification import recognize_spec
from legible.discover.links import published_links

MAX_ARTIFACT_STEPS = 3
FILE = re.compile(r'\.(?:json|ya?ml)$', re.I)
LOCATION = re.compile(r'\b(?:latest|openapi|swagger|specs?|specification|schemas?)\b', re.I)


@dataclass
class ArtifactChain:
    root: str
    steps: dict[str, int] = field(default_factory=dict)
    terminal: set[str] = field(default_factory=set)

    def __post_init__(self):
        self.steps[self.root] = 0

    def follow(self, observation, normalize):
        """Select at most one explicitly linked next step from this response."""
        requested = observation.requested_url
        step = self.steps[requested]
        if requested in self.terminal or step >= MAX_ARTIFACT_STEPS:
            return None
        source = observation.final_url or requested
        media = (observation.content_type or '').split(';')[0].lower()
        if media not in {'text/html', 'application/xhtml+xml'} and recognize_spec(observation.text):
            return None
        root = urlsplit(self.root)
        current = urlsplit(source)
        # A redirect may serve the artifact, but cannot establish a new crawl root.
        if (current.scheme, current.netloc) != (root.scheme, root.netloc):
            return None
        base = unquote(root.path).rstrip('/')
        if not base or not (unquote(current.path).rstrip('/') == base or
                            unquote(current.path).startswith(base + '/')):
            return None
        choices = []
        for order, link in enumerate(published_links(observation.text, media)):
            try:
                target = normalize(urljoin(source, link.href))
            except (ValueError, UnicodeError):
                continue
            if not target or target in self.steps:
                continue
            parsed = urlsplit(target)
            path = unquote(parsed.path)
            if parsed.scheme != 'https' or any(part in {'.', '..'} for part in path.split('/')):
                continue
            same = parsed.netloc == root.netloc and path.startswith(base + '/')
            raw = bool(FILE.search(current.path) and re.search(r'\braw\b|download', link.label, re.I)
                       and FILE.search(path))
            if not same and not raw:
                continue
            filename = path.rstrip('/').rsplit('/', 1)[-1]
            if FILE.search(path):
                relevant_file = LOCATION.search(path[len(base):] + ' ' + link.label) or re.search(
                    r'\b(?:api|contract)\b', filename + ' ' + link.label, re.I)
                if not raw and not relevant_file:
                    continue
                score = 0 if raw else 1 if LOCATION.search(filename + ' ' + link.label) else 2
            elif same and LOCATION.search(filename + ' ' + link.label):
                score = 3
            else:
                continue
            choices.append((score, order, target, link.label, not same or raw))
        if not choices:
            return None
        _, _, target, label, terminal = min(choices)
        self.steps[target] = step + 1
        if terminal:
            self.terminal.add(target)
        return target, label
