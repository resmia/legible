# legible

Legible is being built to inspect a domain's public software-facing surface and
recommend evidence-backed integration improvements. It does not calculate scores.

The current Step 1 scaffold fetches one homepage and writes `report.json` and
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
empty. The full v1 report schema is deferred. Generated reports are local-only.
