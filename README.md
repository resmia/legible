# legible

Legible is being built to inspect a domain's public software-facing surface and
recommend evidence-backed integration improvements. It does not calculate scores.

The current Step 2 scaffold fetches one homepage and writes `report.json` and
`report.md`. Product checks and discovery are not implemented yet. Empty findings
do not mean the site passed an assessment.

```sh
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/legible scan example.com
.venv/bin/pytest
```

A domain defaults to HTTPS. HTTP(S) URLs are accepted and normalized to their
homepage, dropping paths, queries, and fragments. Legacy `legible <url>` input
remains supported. Expected fetch failures produce a concise error and a nonzero
exit status.

Reports retain the prototype's `runs/<timestamp>-<host>/` location and JSON fields:
`url`, `finding_count`, `fix_count`, `findings`, and `fixes`. Both lists are currently
empty. An additive `observations` list retains each successful homepage fetch's
`requested_url`, `final_url`, HTTP `status`, `content_type`, `text`, and `error`.
Markdown shows the source URL and fetch metadata. Failed fetches return an
observation internally; the CLI still exits with an error without writing reports.
Unavailable observation fields are null; an observed empty body is an empty string.
The full v1 report schema is deferred. Generated reports are local-only.
