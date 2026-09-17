"""HTML presentation only: all determinations and remedies come from the engine."""
from html import escape
from urllib.parse import urlsplit

from legible.models import ScanReport
from legible.output.evidence import select_evidence

STATUS = {'pass': 'Clear', 'fail': 'Needs attention', 'unknown': 'Could not verify',
          'not_applicable': 'Not applicable'}
GROUPS = (
    ('Discover', 'Find the right entry point.', ('openapi', 'llms-txt', 'mcp-discovery')),
    ('Access', 'Understand how to make the first request.', ('auth-mechanism', 'key-issuance')),
    ('Recover', 'Handle failures predictably.', ('typed-errors', 'retry-guidance')),
)
COPY = {
    'openapi': ('API specification', 'A machine-readable specification helps software understand available operations and data shapes.'),
    'llms-txt': ('Agent entry point', 'A public documentation index points software toward canonical integration resources.'),
    'mcp-discovery': ('MCP connection', 'A canonical connection location lets an MCP client find the published server.'),
    'auth-mechanism': ('Authentication mechanism', 'An explicit authentication mechanism tells software how to construct authenticated requests.'),
    'key-issuance': ('Credential acquisition', 'A usable acquisition path lets developers obtain the credential needed for a first request.'),
    'typed-errors': ('Structured errors', 'Stable error identifiers let software distinguish failure conditions and respond predictably.'),
    'retry-guidance': ('Retry guidance', 'Actionable retry instructions help clients recover from transient failures safely.'),
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
        fix = f'<section class="remedy"><h4>How to fix</h4><p>{escape(finding.fix)}</p></section>'
    return f'''<details class="finding {finding.state}" id="{finding.id}">
      <summary><span class="finding-heading"><span>{escape(title)}</span>
      <span class="status {finding.state}">{STATUS[finding.state]}</span></span>
      <span class="explanation">{escape(explanation)}</span><span class="detail-hint">Evidence &amp; details</span></summary>
      <div class="finding-body"><h4>What Legible found</h4><p>{escape(finding.title)}</p>
      <h4>Why this matters</h4><p>{escape(why)}</p>{fix}
      <h4>Evidence</h4><ul class="evidence">{''.join(evidence) or '<li>No conclusive evidence was available in the examined surface.</li>'}</ul></div></details>'''


def render_report(report: ScanReport) -> str:
    domain = urlsplit(report.homepage.requested_url).netloc
    classification = report.classification
    types = [SURFACES[t] for t in classification.detected_types if t in SURFACES]
    surface_text = ' · '.join(types) or ('No software-facing surface established' if classification.kind == 'none'
                                       else 'Surface could not be verified')
    counts = {state: sum(f.state == state for f in report.findings) for state in STATUS}
    counts_html = ''.join(f'<span class="status {state}"><b>{count}</b> {STATUS[state].lower()}</span>'
                          for state, count in counts.items() if count)
    summary = ('Start with the findings that need attention; review uncertainty before drawing conclusions.'
               if counts['fail'] else 'Some conclusions could not be verified from the examined public material.'
               if counts['unknown'] else 'The applicable findings are clear in the examined public material.')
    groups = []
    priority = {'fail': 0, 'unknown': 1, 'pass': 2, 'not_applicable': 3}
    for name, description, ids in GROUPS:
        findings = sorted((f for f in report.findings if f.id in ids), key=lambda f: priority[f.state])
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
      <p class="eyebrow">Public surface report</p><h2 id="report-title">{escape(domain)}</h2>
      <p class="surface">{escape(surface_text)}</p><p class="meta">{escape(classification.reason)}</p>
      <div class="counts">{counts_html}</div><p>{summary}</p>
      <p class="meta">This report describes published information, not runtime behavior.</p></header>
      {''.join(groups)}<details class="sources"><summary>Sources examined <span class="meta">({len(sources)})</span></summary>
      <p>{pending} discovery candidates left unexamined. Conclusions retain the engine’s coverage limits.</p>
      <ol>{''.join(sources)}</ol></details></article>'''


def render_page(token: str, report: ScanReport | None = None, target: str = '', error: str = '') -> str:
    report_html = render_report(report) if report else ''
    error_html = f'<p class="error" role="alert" id="input-error">{escape(error)}</p>' if error else ''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1"><title>Legible — public surface report</title>
      <link rel="stylesheet" href="/style.css"><script src="/app.js" defer></script></head>
      <body><main><header class="brand"><a href="/">◩ Legible</a><span>Public software surface</span></header>
      <section class="intro"><h1>See your product the way software sees it.</h1>
      <p>Legible examines your public software-facing surface and shows what another piece of software can discover, understand, and use without guessing.</p></section>
      <form action="/scan" method="post"><input type="hidden" name="token" value="{escape(token)}">
      <label for="domain">Public domain</label><div class="input-row"><input id="domain" name="domain" type="text"
      placeholder="example.com" value="{escape(target)}" required maxlength="2048" spellcheck="false" autocapitalize="none"
      {'aria-invalid="true" aria-describedby="input-error"' if error else ''}>
      <button type="submit">{'Rescan' if report else 'Scan'}</button></div>{error_html}
      <p id="progress" role="status" aria-live="polite"></p></form>{report_html}
      <footer>Legible examines a bounded set of public resources. No accounts or authenticated requests.</footer>
      </main></body></html>'''
