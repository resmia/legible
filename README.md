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

Discovery prioritizes explicit documentation entry points and publisher-provided
indexes/specifications/MCP pointers, then structured file probes. It next selects
API/request-authentication, credential-acquisition, error/schema, and retry/rate-limit links for unresolved checks,
followed by host guesses and secondary documentation. Customer-authentication
marketing does not receive API-authentication priority without developer context.
Core reevaluates the seven pure checks between fetches; discovery uses unresolved
check IDs to reorder candidates. Checks never fetch.
Successful seed HTML and Markdown/text indexes supply links. One
documentation-entry layer and one index layer may supply follow-ups, with a
maximum navigation depth of three; terminal pages do not expand.
Relative links use final response URLs. Origins stay restricted to initial origins
and seed redirect origins. Queries, credentials, non-HTTP(S) URLs and fragments
are rejected or removed; requested and final URLs are deduplicated.

The maximum is **30 fetch-layer calls**, including the homepage and at most 29
published links. No guessed hosts or file paths were added. Discovery stops when
the finite candidate queue is exhausted. Once all seven implemented checks pass
or are explicitly not applicable, discovery skips remaining secondary links and
guesses. Explicit entry/index/specification/MCP pointers still receive attention
because they may expose another integration surface. Unresolved checks can use
the remaining budget; incomplete evidence is never turned into failure to stop.
It does not fill unused capacity after checks settle.
Redirect hops are not separate candidate calls. This is a resource-count cap,
not a byte or elapsed-time budget. The additive JSON `discovery.pending_urls`
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
MCP server documentation with connection instructions, and SDK/CLI documentation
with nearby installation commands. This recognizes published material, not its
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
mappings (using PyYAML); this is not schema validation. An absence failure requires
an established REST surface and explicit 404/410 responses at all examined spec candidates,
including the three fixed probes. Unrecognized or unavailable artifacts are unknown.
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

- `llms-txt` recognizes useful Markdown documentation links in a fetched text index
  at a defined llms/index path or an explicitly published machine-readable index.
  Main-host and documentation-host indexes count; HTML fallbacks and mentions do not.
  Absence fails only with an established surface, examined candidate locations, and
  complete bounded coverage. An unexamined docs-host index keeps the result unknown.
- `typed-errors` recognizes documented JSON error objects, named error codes, and
  OpenAPI error response schemas, including bounded local references. Status lists
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
The existing classifier is unchanged; a recognized connection artifact can establish
MCP applicability for its check even when classification remains uncertain.
