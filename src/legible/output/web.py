"""HTML presentation only: all determinations and remedies come from the engine."""
from html import escape
from urllib.parse import urlsplit

from legible.models import ScanReport
from legible.output.evidence import select_evidence

STATUS = {'pass': 'Clear', 'fail': 'Needs attention', 'unknown': 'Could not verify',
          'not_applicable': 'Not applicable'}
GROUPS = (
    ('Discover', 'Can an agent find the public documentation, specifications, and connection details it needs?', ('openapi', 'llms-txt', 'mcp-discovery')),
    ('Access', 'Can an agent determine how to authenticate, obtain credentials, and make a first request?', ('auth-mechanism', 'key-issuance')),
    ('Recover', 'Can an agent understand a failed request, decide what to do next, and retry safely when appropriate?', ('typed-errors', 'retry-guidance')),
)
COPY = {
    'openapi': ('API specification', 'A machine-readable specification helps software understand available operations and data shapes.'),
    'llms-txt': ('Agent entry point', 'A public documentation index points software toward canonical integration resources.'),
    'mcp-discovery': ('MCP connection', 'A canonical connection location lets an MCP client find the published server.'),
    'auth-mechanism': ('Authentication mechanism', 'An explicit authentication mechanism tells software how to construct authenticated requests.'),
    'key-issuance': ('Credential acquisition', 'A usable acquisition path lets developers obtain the credential needed for a first request.'),
    'typed-errors': ('Machine-readable errors', 'An agent needs to distinguish problems such as invalid credentials, invalid input, rate limits, missing resources, and temporary service failures. Without structured errors, it may guess the wrong response.'),
    'retry-guidance': ('Safe retry guidance', 'Retrying every failure can create duplicate actions or unnecessary load. Never retrying can cause an agent to abandon an operation that would have succeeded later.'),
}
VERIFY = {
    'openapi': 'A publicly reachable machine-readable API specification linked from public documentation or discovery material.',
    'llms-txt': 'A public documentation index or clearly linked entry point an agent can follow.',
    'mcp-discovery': 'Public MCP connection instructions or metadata identifying the server and connection path.',
    'auth-mechanism': 'Public documentation naming the authentication method and showing how it is supplied with a request.',
    'key-issuance': 'Public documentation explaining where or how a user obtains the required credential.',
    'typed-errors': 'A public error schema or example showing stable machine-readable fields such as status, code or type, message, and relevant details.',
    'retry-guidance': 'Public guidance identifying retryable failures and explaining when and how to retry safely.',
}
RECOVER = {
    'typed-errors': (
        'Can an agent reliably interpret a failed response?',
        'Legible checks whether the public documentation defines a consistent, machine-readable error format—for example, an HTTP status, stable error code or type, explanatory message, and relevant field details.'),
    'retry-guidance': (
        'Can an agent determine whether, when, and how to try again?',
        'Legible checks whether the public documentation identifies retryable failures and provides actionable guidance. This could include delay instructions, backoff behavior, rate-limit information, Retry-After, or guidance for avoiding duplicate operations.'),
}

SURFACES = {'rest': 'REST API', 'mcp': 'MCP', 'sdk': 'SDK', 'cli': 'CLI'}


def link(url: str) -> str:
    """Remote evidence is untrusted, including link protocols."""
    label = escape(url)
    try:
        safe = urlsplit(url).scheme in {'http', 'https'}
    except ValueError:
        safe = False
    return f'<a href="{label}" target="_blank" rel="noreferrer">{label}</a>' if safe else label


def provenance(report: ScanReport, index: int) -> str:
    surface = next((s for s in report.discovery.surfaces if s.observation_index == index), None)
    if not surface:
        return ''
    text = f'Discovery: {escape(surface.reason.replace("_", " "))}'
    if surface.source_url:
        text += f' · Linked from {link(surface.source_url)}'
    return f'<p class="meta">{text}</p>'


def finding_card(finding, report: ScanReport) -> str:
    title, why = COPY[finding.id]
    explanation = finding.title.partition(': ')[2] or finding.title
    if finding.state == 'not_applicable':
        return f'''<details class="finding not_applicable" id="{finding.id}">
          <summary><span class="finding-heading"><span>{escape(title)}</span>
          <span class="status not_applicable">Not applicable</span></span>
          <span class="explanation">{escape(explanation)}</span></summary>
          <div class="finding-body"><p>{escape(explanation)}</p></div></details>'''
    explanation = RECOVER.get(finding.id, (explanation, ''))[0]
    check_description = RECOVER.get(finding.id, ('', ''))[1]
    check_description = f'<p>{escape(check_description)}</p>' if check_description else ''
    evidence = []
    for item in select_evidence(finding, report):
        excerpt = f'<blockquote>{escape(item.excerpt)}</blockquote>' if item.excerpt else ''
        evidence.append(f'<li>{link(item.source_url)}{excerpt}'
                        f'<p class="meta">HTTP {item.status if item.status is not None else "unavailable"}'
                        f' · {escape(item.content_type or "Content type unavailable")}'
                        f'{" · " + escape(item.error) if item.error else ""}</p>'
                        f'{provenance(report, item.observation_index)}</li>')
    fix = ''
    if finding.state == 'fail' and finding.fix:
        fix = f'<section class="remedy"><h4>Recommended fix</h4><p>{escape(finding.fix)}</p></section>'
    elif finding.state == 'unknown':
        fix = f'<section><h4>What would verify this</h4><p>{escape(VERIFY[finding.id])}</p></section>'
    return f'''<details class="finding {finding.state}" id="{finding.id}">
      <summary><span class="finding-heading"><span>{escape(title)}</span>
      <span class="status {finding.state}">{STATUS[finding.state]}</span></span>
      <span class="explanation">{escape(explanation)}</span><span class="detail-hint">Evidence &amp; details</span></summary>
      <div class="finding-body"><h4>What Legible found</h4><p>{escape(finding.title)}</p>{check_description}
      <h4>Why this matters</h4><p>{escape(why)}</p>{fix}
      <h4>Evidence</h4><ul class="evidence">{''.join(evidence) or '<li>No conclusive evidence was available in the examined surface.</li>'}</ul></div></details>'''


def render_report(report: ScanReport) -> str:
    domain = urlsplit(report.homepage.requested_url).netloc
    classification = report.classification
    types = [SURFACES[t] for t in classification.detected_types if t in SURFACES]
    surface_text = ' · '.join(types) or ('No software-facing surface established' if classification.kind == 'none'
                                       else 'Surface could not be verified')
    phrases = {'rest': 'a REST API', 'mcp': 'an MCP surface', 'sdk': 'an SDK', 'cli': 'a CLI'}
    detected = [phrases[t] for t in classification.detected_types if t in phrases]
    if detected:
        joined = detected[0] if len(detected) == 1 else ' and '.join(detected) if len(detected) == 2 else ', '.join(detected[:-1]) + ', and ' + detected[-1]
        surface_explanation = f'Legible found public documentation describing {joined}. Other integration surfaces may exist but were not confirmed in the public material examined.'
    else:
        surface_explanation = 'Legible could not confirm a public integration surface in the material examined. Integration surfaces may exist beyond that material.'
    by_id = {finding.id: finding for finding in report.findings}
    fix_ids = GROUPS[1][2] + GROUPS[0][2] + GROUPS[2][2]
    fixes = [by_id[id] for id in fix_ids if id in by_id and by_id[id].state == 'fail' and by_id[id].fix][:3]
    fix_first = ''
    if fixes:
        items = ''.join(f'<li><a href="#{f.id}">{escape(COPY[f.id][0])}</a>: {escape(f.fix)}</li>' for f in fixes)
        fix_first = f'<section class="fix-first"><h3>Fix first</h3><p>These confirmed public-surface issues are most likely to prevent an agent from using the integration successfully.</p><ol>{items}</ol></section>'
    groups = []
    priority = {'fail': 0, 'unknown': 1, 'pass': 2, 'not_applicable': 3}
    for name, description, ids in GROUPS:
        findings = sorted((f for f in report.findings if f.id in ids), key=lambda f: (priority[f.state], ids.index(f.id)))
        cards = ''.join(finding_card(f, report) for f in findings)
        groups.append(f'<section class="group"><div class="group-heading"><h3>{name}</h3><p>{description}</p></div>{cards}</section>')
    sources = []
    for index, item in enumerate(report.discovery.observations):
        sources.append(f'<li><h4>Requested URL</h4>{link(item.requested_url)}'
                       f'<p>Resolved URL: {link(item.final_url) if item.final_url else "Unavailable"}</p>'
                       f'<p>HTTP status: {item.status if item.status is not None else "Unavailable"}'
                       f' · Content type: {escape(item.content_type or "Unavailable")}</p>'
                       f'{provenance(report, index)}<p>Fetch error: {escape(item.error or "None")}</p>'
                       f'<details><summary>Fetched source text</summary><blockquote>{escape(item.text or "")}</blockquote></details></li>')
    pending = len(report.discovery.pending_urls)
    return f'''<article aria-labelledby="report-title"><header class="report-header">
      <p class="eyebrow">PUBLIC SURFACE REPORT</p><h2 id="report-title">{escape(domain)}</h2>
      <p class="surface">Detected public interface</p><p class="surface">{escape(surface_text)}</p>
      <p>{escape(surface_explanation)}</p></header>
      <section class="report-guide"><h3>How to read this report</h3>
      <p>Legible follows the path an agent takes when attempting to use a public integration: finding the entry point, obtaining access, and handling failures. Each finding below shows what Legible could establish from publicly available information.</p></section>
      {fix_first}
      {''.join(groups)}<details class="sources"><summary>Sources examined <span class="meta">({len(sources)})</span></summary>
      <p>{pending} discovery candidates left unexamined. Conclusions retain the engine’s coverage limits.</p>
      <ol>{''.join(sources)}</ol></details>
      <footer><strong>Scope:</strong> Legible reviewed publicly available documentation. It did not sign in, use credentials, or send live API requests.</footer></article>'''


def render_page(token: str, report: ScanReport | None = None, target: str = '', error: str = '') -> str:
    report_html = render_report(report) if report else ''
    error_html = f'<p class="error" role="alert" id="input-error" {"" if error else "hidden"}>{escape(error)}</p>'
    header_action = ('<button type="button" id="scan-another" aria-controls="scan-form" aria-expanded="false">Scan another domain</button>'
                     if report else '<span>Public software surface</span>')
    intro = '' if report else '''<section class="intro"><h1>See your product the way software sees it.</h1>
      <p>Legible examines your public software-facing surface and shows what another piece of software can discover, understand, and use without guessing.</p></section>'''
    footer = '' if report else '<footer>Legible examines a bounded set of public resources. No accounts or authenticated requests.</footer>'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1"><title>Legible — public surface report</title>
      <link rel="stylesheet" href="/style.css"><script src="/app.js" defer></script></head>
      <body><main><header class="brand"><a href="/">◩ Legible</a>{header_action}</header>{intro}
      <form id="scan-form" action="/scan" method="post" {'hidden class="compact-form"' if report else ''}><input type="hidden" name="token" value="{escape(token)}">
      <label for="domain">Public domain</label><div class="input-row"><input id="domain" name="domain" type="text"
      placeholder="example.com" value="{escape(target)}" required maxlength="2048" spellcheck="false" autocapitalize="none"
      {'aria-invalid="true" aria-describedby="input-error"' if error else ''}>
      <button type="submit">Scan</button></div>{error_html}
      <p id="progress" role="status" aria-live="polite"></p></form>{report_html}{footer}
      </main></body></html>'''
