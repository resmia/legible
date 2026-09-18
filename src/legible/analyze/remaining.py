"""Remaining V1 checks: pure interpretation of collected public evidence."""
import json
import re
from urllib.parse import urlsplit, urljoin

import yaml

from legible.analyze.classification import _text
from legible.analyze.mcp import mcp_evidence
from legible.analyze.specification import recognize_spec

ERROR = re.compile(r'\berrors?\b|\b[45]\d\d\b|failure', re.I)
RETRY = re.compile(r'retr(?:y|ies)|backoff|rate.limit|throttl|\b429\b|idempotenc', re.I)
MCP = re.compile(r'\bMCP\b|Model Context Protocol', re.I)
FIELDS = {'code', 'type', 'error', 'error_code', 'request_id', 'parameter'}


def _document(raw):
    try:
        return yaml.safe_load(raw)
    except (yaml.YAMLError, ValueError, RecursionError):
        return None


def _schema_fields(node, document, seen=()):
    """Follow local references only, with cycle/depth bounds; never fetch refs."""
    if not isinstance(node, dict) or len(seen) > 20:
        return False
    ref = node.get('$ref')
    if isinstance(ref, str) and ref.startswith('#/') and ref not in seen:
        target = document
        for key in ref[2:].split('/'):
            target = target.get(key.replace('~1', '/').replace('~0', '~'), {}) if isinstance(target, dict) else {}
        if _schema_fields(target, document, (*seen, ref)):
            return True
    properties = node.get('properties')
    if isinstance(properties, dict) and FIELDS.intersection(properties):
        return True
    return any(_schema_fields(value, document, (*seen, 'child')) for key, value in node.items()
               if (key in {'schema', 'content'} or isinstance(key, str)
                   and re.fullmatch(r'application/(?:[\w.+-]+\+)?json', key)) and isinstance(value, dict)) or any(
        _schema_fields(value, document, (*seen, 'child'))
        for key in ('allOf', 'oneOf', 'anyOf')
        for value in (node[key] if isinstance(node.get(key), list) else []))


def _spec_errors(raw):
    if not recognize_spec(raw):
        return None
    doc = _document(raw)
    for path, item in doc['paths'].items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method not in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'} or not isinstance(operation, dict):
                continue
            responses = operation.get('responses', {})
            if not isinstance(responses, dict):
                continue
            for status, response in responses.items():
                if re.fullmatch(r'[45](?:\d\d|XX)', str(status), re.I) and _schema_fields(response, doc):
                    return f'{method.upper()} {path}: HTTP {status} response has structured error fields (local references only).'
    return None


def _structured(text):
    sdk = re.search(r'(?:SDK errors?|except \w*Error|catch\s*\([^)]*Error).{0,240}\b\w+\.(?:code|type|error_code)\s*={2,3}\s*["\'][\w.-]+["\'].{0,160}', text, re.I)
    if sdk and not re.search(r'planned|example only|not returned', sdk[0], re.I):
        return sdk[0]
    # Require an error context adjacent to an actual JSON object, not exception code.
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{', text):
        try:
            value, length = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        context = text[max(0, match.start()-180):match.start()+length+100]
        if (isinstance(value, dict) and ERROR.search(context)
                and not re.search(r'catch\s*\(|except\b|throw\b|console\.log|example only|not returned|planned', context, re.I)):
            model = value.get('error') if isinstance(value.get('error'), dict) else value
            error_context = model is not value or re.search(
                r'error (?:response|object)|errors? (?:returned|return)|returns? an? error', context, re.I)
            if error_context and any(
                    isinstance(model.get(key), (str, int)) and not isinstance(model.get(key), bool)
                    and re.fullmatch(r'[\w.-]+', str(model[key]))
                    for key in ('code', 'type', 'error_code')):
                return context
    match = re.search(r'\berror (?:code|type)\s*[`:\s]+[A-Z][A-Z_]{2,}\b[^.!?]{0,120}', text)
    if match and not re.search(r'planned|example only|not returned', text[max(0, match.start()-80):match.end()], re.I):
        return match[0]
    return _rendered_error_model(text)


def _rendered_error_model(text):
    """Require local field definitions and stable identifiers, not page keywords."""
    for anchor in re.finditer(r'\berrors?\b', text, re.I):
        section = text[anchor.start():anchor.end()+2400]
        if not re.search(r'\berror (?:object|response|types?|codes?)\b|\btype of error\b|errors? attributes', section, re.I):
            continue
        if re.search(r'planned|example only|not returned|coming soon|catch\s*\(|except\b|throw\s', section, re.I):
            continue
        # Rendered tables lose markup in visible text. Require a field/type row
        # plus semantics or enumerated identifiers within the same small region.
        identifier = re.search(r'\b(?:code|error_code|type)\b[`\s|:*–-]*(?:nullable\s+)?(?:string|enum)\b', section, re.I)
        named = re.findall(r'\b[a-z][a-z0-9]*_(?:[a-z0-9]+_)*[a-z0-9]+\b', section)
        stable = re.search(r'\b(?:stable|machine.readable|identif(?:ier|ies|ying)|one of|possible values|enum|category|categories)\b', section, re.I)
        members = re.search(r'\bmessage\b[`\s|:*–-]*(?:nullable\s+)?string\b', section, re.I)
        companion = re.search(r'\b(?:param|parameter|request_id)\b[`\s|:*–-]*(?:string|nullable)\b', section, re.I)
        named_types = re.search(r'\berror (?:types|codes)\s+(?:are|include|can be|one of)\b', section, re.I)
        enum_list = re.search(
            r'(?:one of|possible values\s*:|error (?:types|codes) (?:are|include))\s+'
            r'[`\"\']?[a-z][\w-]*[`\"\']?\s*(?:,|\band\b)\s*[`\"\']?[a-z][\w-]*', section, re.I)
        categories = len(set(named)) >= 2 or enum_list
        status_codes = re.search(r'error codes?.{0,120}(?:status|HTTP|meaning)', section, re.I) and re.search(r'[a-z]+_[a-z_]+\s*[|:]\s*[45]\d\d\s*[|:]\s*\w+', section)
        if (status_codes or identifier and stable and (members and companion or categories)
                or named_types and categories):
            return section
    return None


def _retry(text):
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        if re.search(r'\b(?:not supported|not provided|not returned|do not|does not|never retry|coming soon|planned)\b', sentence, re.I):
            continue
        if (re.search(r'retry.after', sentence, re.I) and re.search(r'wait|seconds|delay|header', sentence, re.I)
                or re.search(r'(?:exponential|exponentially).*back.?off|back.?off.*(?:exponential|exponentially)', sentence, re.I)
                and re.search(r'retr(?:y|ies)|use|apply|recommend|wait', sentence, re.I)
                or re.search(r'idempotenc', sentence, re.I) and re.search(r'retr(?:y|ies)', sentence, re.I) and re.search(r'safe|same|reuse|prevent', sentence, re.I)
                or re.search(r'retr(?:y|ies)', sentence, re.I) and re.search(r'\b(?:429|5\d\d|timeout|transient)\b', sentence, re.I) and re.search(r'wait|backoff|after|automatically|retryable|should retry', sentence, re.I)):
            return sentence
    for match in re.finditer(r'\b(?:[45]\d\d|connection (?:failure|error)|timeout)\b', text, re.I):
        section = text[max(0, match.start()-80):match.end()+600]
        if re.search(r'planned|coming soon|example only', section, re.I):
            continue
        if (re.search(r'retryable|safe to retry', section, re.I)
                and re.search(r'backoff|wait|delay|fix.{0,80}request|non.retryable|do not retry', section, re.I)):
            return section
    return None


def remaining_checks(discovery, classification, finding):
    observations = discovery.observations
    texts = {i: t for i, o in enumerate(observations) if (t := _text(o))}
    types = set(classification.detected_types)
    known = bool(types)
    complete = not discovery.pending_urls and bool(texts.get(0))
    # Failed advertised resources leave coverage open; absent speculative probes do not.
    complete &= all(s.observation_index in texts or (
        s.reason != 'published_link' and observations[s.observation_index].status in {404, 410})
        for s in discovery.surfaces)
    context = set(range(len(observations)))
    results = []

    indexes = {s.observation_index for s in discovery.surfaces
               if re.search(r'/(?:llms(?:-full)?\.txt|index\.(?:md|txt))$', urlsplit(s.url).path, re.I)
               or s.reason == 'published_link' and re.search(
                   r'machine.readable.*(?:index|documentation)', s.link_text or '', re.I)}
    usable = []
    for i in indexes & texts.keys():
        o = observations[i]
        # HTML fallbacks and articles about llms.txt are not published text indexes.
        if (o.content_type or '').split(';')[0] not in {'text/plain', 'text/markdown'}:
            continue
        links = re.findall(r'\[([^]\n]+)\]\((https?://[^\s)]+|/[^\s)]*)\)', o.text)
        instructions = (re.search(r'API base URL|API routes|bearer|API key|setup|canonical.*(?:contract|reference)', o.text, re.I)
                        and re.search(r'https?://|GET /|POST /', o.text)
                        and len(o.text.split()) >= 8)
        if instructions or any(re.search(r'docs|documentation|API|reference|auth|SDK|MCP|guide|quickstart|error', label, re.I) for label, _ in links):
            usable.append((i, o.text[:700]))
    attempted = {u for o in observations for u in (o.requested_url, o.final_url) if u}
    docs_origins = {urljoin(o.final_url or o.requested_url, '/llms.txt')
                    for i, o in enumerate(observations) if i in texts
                    and (urlsplit(o.final_url or o.requested_url).hostname or '').startswith(('docs.', 'developer.', 'developers.'))}
    index_coverage = docs_origins <= attempted or bool(usable)
    if usable:
        state, reason = 'pass', 'Fetched public documentation index contains useful navigation.'
    elif classification.kind == 'none':
        state, reason = 'not_applicable', 'No public developer surface observed.'
    elif known and complete and index_coverage and indexes and all(observations[i].status in {404, 410} for i in indexes):
        state, reason = 'fail', 'Examined index candidates are absent in the bounded public surface.'
    else:
        state, reason = 'unknown', 'Index coverage or the usefulness of fetched candidate content is inconclusive.'
    results.append(finding('llms-txt', 'Machine-readable documentation index', state, reason, indexes | context, usable))

    structured = []
    uncertain_error_schema = False
    for i, t in texts.items():
        raw = observations[i].text
        # Specs must satisfy response-schema rules, not prose/example heuristics.
        spec = recognize_spec(raw)
        match = _spec_errors(raw) if spec else _structured(t)
        uncertain_error_schema |= bool(spec and ERROR.search(t) and not match)
        if match:
            structured.append((i, match))
    retry = [(i, match) for i, t in texts.items() if (match := _retry(t))]
    for id, title, matches, relevant in (
        ('typed-errors', 'Structured errors', structured, ERROR),
        ('retry-guidance', 'Retry guidance', retry, RETRY),
    ):
        network = 'rest' in types or any(re.search(r'\b(?:HTTPS? (?:requests?|transport|API)|network requests?|remote (?:server|API)|429)\b|(?:connect|endpoint)[^.!?]{0,100}https?://', t, re.I) for t in texts.values())
        applicable = 'rest' in types or (known and (bool(matches) or network))
        examined = [(i, t) for i, t in texts.items() if relevant.search(t)]
        if applicable and matches:
            state, reason = 'pass', 'Public documentation provides actionable structured evidence.'
        elif classification.kind == 'none' or known and not applicable:
            state, reason = 'not_applicable', 'Observed integration does not establish applicable network/error semantics.'
        elif (applicable and complete and examined and
              (id == 'retry-guidance' or not uncertain_error_schema
               and not any(re.search(r'[`\"](?:code|type|error_code|request_id)[`\"]', t) for _, t in examined)
               and any(re.search(r'\b[45]\d\d\b|errors? (?:return|response)|returns? .*errors?', t, re.I) for _, t in examined))):
            state, reason = 'fail', 'Examined relevant documentation provides no actionable '+('structured error semantics.' if id == 'typed-errors' else 'retry guidance.')
        else:
            state, reason = 'unknown', 'Relevant documentation coverage or applicability remains incomplete or ambiguous.'
        results.append(finding(id, title, state, reason, context, matches or examined))

    providers, connections = [], []
    mcp_indices = {i for i, t in texts.items() if MCP.search(t)}
    ambiguous_mcp_artifact = False
    for i, t in texts.items():
        o = observations[i]
        provider, connection = mcp_evidence(t, o.text, o.final_url or o.requested_url)
        if provider:
            providers.append((i, provider))
        if connection:
            connections.append((i, connection))
        if 'server-card' in o.requested_url and not connection:
            ambiguous_mcp_artifact = True
    established = 'mcp' in types or bool(providers)
    if established and connections:
        state, reason = 'pass', 'Public MCP connection instructions or metadata identify a connection path.'
    elif not established:
        state, reason = 'not_applicable', 'No MCP surface established in the collected evidence.'
    elif complete and mcp_indices and not ambiguous_mcp_artifact:
        state, reason = 'fail', 'Examined MCP documentation provides no usable public connection descriptor.'
    else:
        state, reason = 'unknown', 'MCP is established but connection evidence remains incomplete or inaccessible.'
    results.append(finding('mcp-discovery', 'MCP discovery', state, reason, mcp_indices | context, connections))
    return results
