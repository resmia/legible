# legible

Legible is being built to inspect a domain's public software-facing surface and
recommend evidence-backed integration improvements. It does not calculate scores.

Legible discovers a bounded set of public resources, classifies the surface,
and assesses seven capabilities using only collected observations. The CLI writes
`report.json` and `report.md`; a local browser experience presents the same analysis.

```sh
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/legible scan example.com
.venv/bin/pytest
```

For the local browser experience:

```sh
.venv/bin/legible web
```

Open `http://127.0.0.1:8765`, enter a public domain such as `example.com`, and
select **Scan**. Use `legible web --port 8888` to choose another port. Ctrl+C stops
the service. It binds only to loopback and uses the Python standard library;
there are no additional web dependencies or frontend build steps.

The report groups findings into **Discover**, **Access**, and **Recover**. Expand
a finding to inspect what Legible found, why it matters, evidence and provenance,
and engine-generated remediation for confirmed failures. Statuses read **Clear**,
**Needs attention**, **Could not verify**, and **Not applicable**. Counts are not
a score. Mixed surfaces display the classifier's established individual types.
The collapsed **Sources examined** section retains fetch and discovery details.

Browser scans are ephemeral: no report files, database, or scan history are saved.
Use the CLI when you want JSON and Markdown files. Rescan runs a fresh scan.
The service accepts one active scan at a time; it shows a waiting message during
the request, without incremental progress or cancellation. The existing fetch
ceiling is not an elapsed-time budget, so slow sources can delay a result.
This is a local prototype server, not a deployment service.

Both presentations call `core.scan_report()` and consume the same typed
`ScanReport`. The existing `core.scan()` still writes reports and returns their
directory. Analysis, discovery, classification, internal states, and serialized
JSON fields remain unchanged.

A domain defaults to HTTPS. HTTP(S) URLs are accepted and normalized to their
homepage, dropping paths, queries, and fragments. Legacy `legible <url>` input
remains supported. Homepage failures remain observations; bounded discovery continues and reports
preserve uncertainty. Invalid input still produces a nonzero exit status.

Reports retain the prototype's `runs/<timestamp>-<host>/` location and JSON fields:
`url`, `finding_count`, `fix_count`, `findings`, and `fixes`. Findings now contain `id`, `title`, `state`, `source_url`, `evidence`, and `fix`;
states are `pass`, `fail`, `not_applicable`, and `unknown`. Evidence includes an
observation index, source URL, HTTP status, content type, error, and excerpt.
Fixes remain a list of remediation strings for failing checks only. An additive `observations` list retains every attempted fetch's
`requested_url`, `final_url`, HTTP `status`, `content_type`, `text`, and `error`.
Markdown shows source URLs, fetch metadata, and discovery provenance. Unknown findings describe evidence limits without prescribing defect remediation.
Unavailable observation fields are null; an observed empty body is an empty string.
The full v1 report schema is deferred. Generated reports are local-only.

Discovery tries the homepage, `docs.`, `api.`, `developer.`, and `developers.`
hosts, and these six files on the input origin: `/llms.txt`, `/openapi.json`,
`/openapi.yaml`, `/swagger.json`, `/.well-known/mcp-server-card`, and
`/.well-known/mcp/server-card.json`. Host guesses preserve the scheme and port,
strip a leading `www.`, and are skipped for IP addresses and single-label hosts.

Discovery re-ranks published candidates after each fetch using the seven unresolved
checks. Explicit OpenAPI/Swagger links, actionable retry descriptions, and error
material precede generic navigation and speculative probes. Authentication and
credential pointers outrank ordinary tutorials. Entry points and MCP/CLI/SDK links
can reveal additional surfaces even after the existing checks settle.

Successful HTML and Markdown/text resources may supply follow-ups within a maximum
navigation depth of three. Link labels, nearby context, and Markdown descriptions
are retained; navigation headings do not make every link relevant. Canonical
plain-text contract URLs also count. Queries and embedded credentials are rejected;
fragments are removed; requested and final URLs are deduplicated.

Explicit high-signal publisher links may admit at most three additional related
origins and two external artifacts. Related origins use the complete input host
(with only `www.` removed) as an anchor, not a guessed registrable domain; a host
suffix alone never grants access. External artifacts require a strong formal-spec,
official-source, or canonical-doc pointer, or a documentation delegation from the
homepage. External pages normally remain leaves. For an unresolved formal-spec
check, one explicitly delegated artifact can start a single selected trail with at
most three additional fetches: relevant repository directory, JSON/YAML file page,
and its directly linked raw file. Traversal stays within the published repository
path; a directly linked raw file is an exact terminal exception. Every step counts
against the same 30-fetch ceiling and retains its publishing page and reason.
At the ordinary depth boundary, one explicit formal-spec publication page may
supply that external delegation. Published Markdown changelog indexes precede
individual release navigation; JavaScript is not parsed or executed.
New origins require HTTPS and public DNS answers. Origin-validation attempts are
also capped. The fetch layer validates and pins public IP addresses on each
connection, revalidates redirects, rejects HTTPS downgrades, and disables implicit
proxies. Explicit loopback targets remain available for local testing, with no
public-to-loopback redirects. Requests use an honest Legible user agent, general documentation Accept headers,
and no credentials or cookies. Redirects rebuild only those public headers, reject
loops and downgrades, and independently validate destinations. Nonstandard public
ports and scoped/transition addresses are rejected. Each decoded response is limited
to 16 MiB while streaming, including gzip/deflate responses; truncated or conflicting
lengths are rejected. Five redirects share a 15-second request deadline with socket
operations and streamed body reads. Blocking OS DNS and an in-progress socket/header
read cannot be preempted by that deadline; there is no overall scan deadline.
URL credentials and query values are redacted from retained URL metadata.

The maximum is **30 fetch-layer calls**, including the homepage and at most 29
published links. No guessed hosts or file paths were added. Discovery stops when
the finite candidate queue is exhausted. Once all seven implemented checks pass
or are explicitly not applicable, discovery skips remaining secondary links and
guesses. Explicit entry/index/specification/MCP pointers still receive attention
because they may expose another integration surface. Unresolved checks can use
the remaining budget; incomplete evidence is never turned into failure to stop.
It does not fill unused capacity after checks settle.
Redirect hops are not separate candidate calls. This is a resource-count cap,
not an overall byte or elapsed-time budget. The additive JSON `discovery.pending_urls`
field records candidates left unexamined when discovery stops, allowing
checks to preserve uncertainty. The discovery object also records caps and surfaces.
Each entry records `url`, `reason` (`homepage`, `likely_host`, `public_file`, or
`published_link`), `source_url`, `link_text`, and an `observation_index` into
`observations`. These are attempted candidates, not verified capabilities.

The additive `classification` object contains `kind`, `detected_types`, `reason`,
and `evidence`. Categories are `rest`, `mcp`, `sdk`, `cli`, `mixed`, `none`, and
`unknown`. Evidence records the observation index, final/source URL, signal, and
excerpt; the index links to unchanged fetch metadata and discovery provenance.
Markdown renders the same classification and evidence.

Classification performs no network activity. Narrow signals include OpenAPI or
Swagger JSON/YAML document shapes, explicit API reference/REST documentation or
REST API prose with HTTP endpoint examples,
affirmative MCP provider documentation or connection metadata, and SDK/CLI documentation
with installation or CLI usage instructions. Credential-stub support for third-party
MCP servers and incidental MCP mentions do not establish a provider surface. This recognizes published material, not its
validity or runtime behavior. Multiple observed types produce `mixed`. Specification
recognition checks only the version and root info/paths mappings.
Unrecognized discovery artifacts remain uncertain without a supported signal.

`none` means no software-facing evidence in the bounded examined surface, not
absence across the whole site. It requires readable homepage content, completed
initial probes, readable responses or explicit 404/410 responses, no ambiguous
developer hints, and no reached published-link cap. Incomplete or ambiguous
material produces `unknown`. Incidental keywords and candidate URLs alone never
establish a positive type. Positive types do not imply exhaustive coverage.

The seven checks are deterministic and make no network requests. OpenAPI recognizes
JSON and safely parsed YAML with root version, info, and paths
mappings (using PyYAML); this is not schema validation. An established REST surface
without a verified formal specification remains unknown, including when speculative
probes return 404/410. Prose contracts and llms.txt are not formal specifications.
Authentication requires explicit machine-authentication prose; login UI and isolated
keywords are insufficient. Credential issuance separately requires an acquisition
action and destination for the documented credential. Explicit no-authentication
statements make the authentication checks not applicable. Conflicting statements,
unresolved documentation, and uncertain applicability remain unknown. Negative
findings describe the bounded examined documentation, not the entire site.

Failed speculative hosts remain recorded but do not by themselves describe
documented evidence as blocked.

These narrow text rules can miss valid wording, structured security
schemes, and credential paths beyond the existing discovery cap. No authenticated
requests or behavioral validation are implemented.

Step 6 adds the remaining four V1 checks without changing the report schema:

- `llms-txt` recognizes useful documentation links or concise integration instructions in a fetched text index
  at a defined llms/index path or an explicitly published machine-readable index.
  Main-host and documentation-host indexes count; HTML fallbacks and mentions do not.
  Absence fails only with an established surface, examined candidate locations, and
  complete bounded coverage. An unexamined docs-host index keeps the result unknown.
- `typed-errors` recognizes documented JSON error objects, named error codes, and
  rendered attribute/code tables, SDK error-attribute examples, and OpenAPI error
  response schemas, including bounded local references. Status lists
  and generic error prose cannot pass. A failure requires examined exposed error
  semantics and complete coverage; ambiguous prose remains unknown.
- `retry-guidance` recognizes Retry-After instructions, exponential backoff, safe
  idempotent retries, and retry rules tied to transient conditions. Bare rate limits
  and status codes cannot pass. Local-only integrations can be not applicable.
- `mcp-discovery` recognizes explicit public MCP URLs/setup commands and supported
  JSON connection descriptors (server-card transport or mcpServers configuration).
  A non-MCP surface is not applicable. An established MCP surface fails only after
  complete bounded coverage without connection information.

All conclusions retain observation evidence. Positive evidence can settle a check
while other sources remain unavailable; pending or inaccessible documentation
prevents absence-based failures. Unknown findings never generate remediation.
These conservative recognizers are not exhaustive documentation/schema parsers:
unsupported index formats, MCP metadata variants, external schema references,
ambiguous wording, and inaccessible or deeply nested documentation may remain unknown.
Classification and the MCP check share provider/connection recognition. Browser evidence
selection prefers direct passages and deduplicates equivalent HTML/Markdown excerpts;
full fetched observations remain under Sources examined.


Fetched evidence is shared across all seven checks; the discovery reason selects
where to look, not which evaluator may inspect a response. Block-page detection
uses response-level challenge titles or short challenge bodies, not error-message
phrases anywhere in a documentation page. The original bounded body remains the
source of truth, with immutable derived text/heading/list/table/code-block views.
Existing link extraction and discovery provenance remain available from that body.

Real fetch observations now include optional additive `metadata` (method, safe
redirect hops, encoded bytes read, decoded bytes retained, truncation, and content
encoding) and `canonical_url` in JSON. Legacy observations without transport
metadata retain their existing serialized fields. These canonical URLs are
traceability keys; they do not replace discovery's conservative URL admission or
merge observations. HEAD bodies are never evidence, and an injected prior HEAD
observation cannot mark a document content-fetched; production scans use GET only.

`analyze.diagnostics.diagnose_evidence` is a pure internal inspection helper over
these same observations. It distinguishes failed fetches, unsupported responses,
unavailable/truncated bodies, evaluator eligibility, examined but unrecognized
evidence, and exhausted budgets. An explicit expected URL can be diagnosed as
undiscovered; the helper does not invent missing URLs or make network requests.
Diagnostic output does not change finding states or the browser presentation.
