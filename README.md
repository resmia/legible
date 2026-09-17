# legible

Legible is being built to inspect a domain's public software-facing surface and
recommend evidence-backed integration improvements. It does not calculate scores.

Build Step 5 discovers a bounded set of public resources, classifies the surface,
and assesses `openapi`, `auth-mechanism`, and `key-issuance` using only collected
observations. It writes `report.json` and `report.md`.

```sh
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/legible scan example.com
.venv/bin/pytest
```

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

Discovery prioritizes publisher-provided indexes/specifications, authentication and
credentials, API references/errors/retry/MCP setup, then general documentation;
fixed guesses come last. Successful seed HTML and Markdown/text indexes supply
links. One documentation-entry layer and one index layer may supply follow-ups,
with a maximum navigation depth of three; terminal pages do not expand.
Relative links use final response URLs. Origins stay restricted to initial origins
and seed redirect origins. Queries, credentials, non-HTTP(S) URLs and fragments
are rejected or removed; requested and final URLs are deduplicated.

The maximum is **30 fetch-layer calls**, including the homepage and at most 29
published links. No guessed hosts or file paths were added. Discovery stops when
the finite candidate queue is exhausted. Once published follow-ups are examined
and all three implemented checks are settled positively or not applicable, the
scan skips remaining guesses. It does not fill unused capacity.
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
Swagger JSON document shapes, explicit API reference/REST documentation or REST API prose with HTTP endpoint examples,
MCP server documentation with connection instructions, and SDK/CLI documentation
with nearby installation commands. This recognizes published material, not its
validity or runtime behavior. Multiple observed types produce `mixed`. JSON spec
recognition is deliberately limited; YAML and unrecognized discovery artifacts
remain uncertain unless documentation supplies a supported signal.

`none` means no software-facing evidence in the bounded examined surface, not
absence across the whole site. It requires readable homepage content, completed
initial probes, readable responses or explicit 404/410 responses, no ambiguous
developer hints, and no reached published-link cap. Incomplete or ambiguous
material produces `unknown`. Incidental keywords and candidate URLs alone never
establish a positive type. Positive types do not imply exhaustive coverage.

The three checks are deterministic and make no network requests. OpenAPI recognizes
JSON document shapes and a narrow YAML subset with root version, info, and paths
mappings; this is not schema validation. An absence failure requires an established
REST surface and explicit 404/410 responses at all examined spec candidates,
including the three fixed probes. Unrecognized or unavailable artifacts are unknown.
Authentication requires explicit machine-authentication prose; login UI and isolated
keywords are insufficient. Credential issuance separately requires an acquisition
action and destination for the documented credential. Explicit no-authentication
statements make the authentication checks not applicable. Conflicting statements,
unresolved documentation, and uncertain applicability remain unknown. Negative
findings describe the bounded examined documentation, not the entire site.

These narrow text rules can miss valid wording, complex YAML, structured security
schemes, and credential paths beyond the existing discovery cap. No later checks,
authenticated requests, or behavioral validation are implemented.
