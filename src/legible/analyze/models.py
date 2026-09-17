"""Evidence-backed v1 findings; observation indices reference the saved report."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FindingEvidence:
    observation_index: int
    source_url: str
    status: int | None
    content_type: str | None
    error: str | None
    excerpt: str


@dataclass(frozen=True)
class Finding:
    id: str
    title: str
    state: Literal['pass', 'fail', 'not_applicable', 'unknown']
    source_url: str | None
    evidence: list[FindingEvidence]
    fix: str | None
