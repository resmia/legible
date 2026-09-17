"""Pure, conservative checks over the bounded observations already collected."""
import re
from urllib.parse import urlsplit

from legible.analyze.classification import SurfaceClassification, _text
from legible.analyze.specification import recognize_spec
from legible.analyze.models import Finding, FindingEvidence
from legible.discover.surfaces import DiscoveryResult
from legible.fix.fixer import remediation

SPEC_PATHS = {'/openapi.json', '/openapi.yaml', '/swagger.json'}
BLOCKED = re.compile(r'access denied|verify you are human|captcha|enable javascript|sign in to continue', re.I)
NEGATIVE = re.compile(r'\b(?:not|never|unsupported|planned|might|may|could|example only|coming soon)\b', re.I)
MECHANISM = re.compile(r'\b(?:API[ -]keys?|bearer tokens?|OAuth(?: 2(?:\.0)?)?|signed requests?|HTTP Basic(?: Auth(?:entication)?)?|mutual TLS|mTLS|HMAC)\b', re.I)
CONTEXT = re.compile(r'\b(?:API|requests?|SDK|CLI|MCP|server)\b', re.I)
AUTH_ACTION = re.compile(r'\b(?:authenticate[sd]?|authentication|requires?|uses?|send|include|authorize|authorization)\b', re.I)
NO_AUTH = re.compile(r'\b(?:API|requests?|SDK|CLI|MCP server)\b[^.!?]{0,100}\b(?:requires? no authentication|does not require (?:authentication|credentials)|no (?:authentication|credentials) (?:is|are) required)\b', re.I)
ACQUIRE = re.compile(r'\b(?:create|generate|obtain|get|issue|request|copy|exchange|register|find|view|retrieve)\b', re.I)
DESTINATION = re.compile(r'\b(?:dashboard|console|settings|developer portal|token endpoint|authorization endpoint|administrator|support|account)\b|https?://', re.I)


def _spec(observation):
    return recognize_spec(observation.text) if _text(observation) is not None else None


def analyze_surface(discovery: DiscoveryResult, classification: SurfaceClassification) -> list[Finding]:
    observations = discovery.observations
    texts = {i: _text(o) for i, o in enumerate(observations)}
    spec_indices = {i for i, o in enumerate(observations) if urlsplit(o.requested_url).path in SPEC_PATHS}
    for s in discovery.surfaces:
        if re.search(r'openapi|swagger', f'{s.url} {s.link_text or ""}', re.I):
            spec_indices.add(s.observation_index)
    specs = {i: value for i, o in enumerate(observations) if (value := _spec(o))}
    docs = {e.observation_index for e in classification.evidence if e.signal.endswith('-documentation')}
    docs.update(s.observation_index for s in discovery.surfaces
                if s.reason in {'likely_host', 'published_link'} and s.observation_index not in spec_indices)
    # Homepage prose can supplement an established integration surface.
    if observations and texts.get(0) and NO_AUTH.search(texts[0]):
        docs.add(0)
    readable = {i: t for i in docs if (t := texts.get(i)) and not BLOCKED.search(t)
                and (observations[i].content_type or '').split(';')[0] in
                {'text/html', 'application/xhtml+xml', 'text/plain', 'text/markdown'}}
    readable = {i: t for i, t in readable.items() if len(t.split()) >= 4 and re.search(
        r'REST(?:ful)? API|API reference|authentication|authenticate|API[ -]keys?|bearer|OAuth|HTTP Basic|credentials?|API requests?|SDK|CLI|MCP server', t, re.I)
        and not re.fullmatch(r'(?:login|log in|sign in|sign up|signup|\s)+', t, re.I)}
    unresolved = any(i not in readable and not (
        observations[i].status in {404, 410} and any(s.observation_index == i and s.reason == 'likely_host'
                                                   for s in discovery.surfaces)) for i in docs)
    unresolved |= bool(discovery.pending_urls)
    speculative = {s.observation_index for s in discovery.surfaces if s.reason == 'likely_host'}
    unavailable = any(
        (texts.get(i) is None or BLOCKED.search(texts.get(i) or ''))
        for i in docs - speculative)
    unavailable |= bool(observations and texts.get(0) is None)
    unresolved |= bool(observations and texts.get(0) is None)
    statements = [(i, sentence.strip()) for i, t in readable.items()
                  for sentence in re.split(r'(?<=[.!?])\s+', t)]
    auth = [(i, s) for i, s in statements if MECHANISM.search(s) and (CONTEXT.search(s) or re.search(r'HTTP Basic|bearer|OAuth|mTLS|mutual TLS|HMAC', s, re.I))
            and AUTH_ACTION.search(s) and not NEGATIVE.search(s)]
    no_auth = [(i, s) for i, s in statements if NO_AUTH.search(s)]
    issuance = [(i, s) for i, s in statements if MECHANISM.search(s) and ACQUIRE.search(s)
                and DESTINATION.search(s) and not NEGATIVE.search(s)
                and any(MECHANISM.search(a).group().lower().rstrip('s') ==
                        MECHANISM.search(s).group().lower().rstrip('s') for _, a in auth)]

    def finding(id, title, state, reason, indices, matches=()):
        indices = set(indices) | {e.observation_index for e in classification.evidence
                                  if e.signal.endswith('-documentation') or e.signal == 'api-spec-document'}
        excerpts = {}
        for index, excerpt in matches:
            excerpts[index] = (excerpts.get(index, '') + ' ' + excerpt).strip()
        evidence = [FindingEvidence(i, observations[i].final_url or observations[i].requested_url,
                    observations[i].status, observations[i].content_type, observations[i].error,
                    excerpts.get(i, (texts.get(i) or 'No readable body')[:300]))
                    for i in sorted(indices)]
        # Classification is itself backed by the same stored observations.
        evidence = evidence or [FindingEvidence(e.observation_index, e.source_url,
                    observations[e.observation_index].status, observations[e.observation_index].content_type,
                    observations[e.observation_index].error, e.excerpt) for e in classification.evidence]
        fix = remediation(id, state)
        return Finding(id, title + ': ' + reason, state, evidence[0].source_url if evidence else None, evidence, fix)

    known = bool(classification.detected_types) or bool(specs)
    absent = classification.kind == 'none'
    if specs:
        state, reason = 'pass', 'Recognizable public specification fetched.'
    elif classification.kind != 'unknown' and 'rest' not in classification.detected_types:
        state, reason = 'not_applicable', 'No REST surface established in the observed classification.'
    elif 'rest' not in classification.detected_types:
        state, reason = 'unknown', 'REST applicability is unresolved.'
    elif (SPEC_PATHS <= {urlsplit(observations[i].requested_url).path for i in spec_indices}
          and all(observations[i].status in {404, 410} for i in spec_indices)
          and not discovery.pending_urls and texts.get(0) is not None):
        state, reason = 'fail', 'Examined spec locations returned 404/410; no specification found in this bounded scan.'
    else:
        state, reason = 'unknown', 'Spec coverage is incomplete or responses are unreadable, ambiguous, or unrecognized.'
    results = [finding('openapi', 'Public API specification', state, reason, spec_indices | specs.keys(), specs.items())]
    if absent:
        state, reason = 'not_applicable', 'No public integration surface observed.'
    elif no_auth and auth:
        state, reason = 'unknown', 'Authentication statements conflict or have different scopes.'
    elif no_auth:
        state, reason = 'not_applicable', 'Documentation explicitly says authentication is unnecessary.'
    elif auth:
        state, reason = 'pass', 'Public documentation describes request authentication.'
    elif not known:
        state, reason = 'unknown', 'Integration applicability is unresolved.'
    elif unresolved or not readable or any(MECHANISM.search(t) for t in readable.values()):
        state = 'unknown'
        reason = ('Some relevant evidence was unavailable or blocked; coverage is incomplete.' if unavailable
                  else 'Relevant discovery candidates remain unexamined; authentication evidence is inconclusive.'
                  if discovery.pending_urls
                  else 'Fetched documentation was examined but authentication evidence remains inconclusive.')
    else:
        state, reason = 'fail', 'Examined integration documentation does not clearly explain request authentication.'
    results.append(finding('auth-mechanism', 'Authentication mechanism', state, reason, docs, auth + no_auth))
    if state == 'pass':
        if issuance:
            state, reason = 'pass', 'Documentation explains an acquisition path for the documented credential.'
        elif unresolved:
            state, reason = 'unknown', 'Credential acquisition may be in unresolved documentation.'
        else:
            state, reason = 'fail', 'Authentication is documented, but examined documentation gives no credential acquisition path.'
    elif state != 'not_applicable':
        state, reason = 'unknown', 'Credential requirements or authentication mechanism remain unresolved.'
    results.append(finding('key-issuance', 'Credential issuance', state, reason, docs, auth + issuance + no_auth))
    return results
