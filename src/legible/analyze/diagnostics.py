"""Internal, pure diagnostics over the same observations and discovery provenance."""
from dataclasses import dataclass
from legible.discover.surfaces import IMPLEMENTED_CHECKS, MAX_FETCHES


@dataclass(frozen=True)
class ObservationDiagnostic:
    observation_index: int
    canonical_url: str
    availability: str
    normalized_characters: int
    evaluator_checks: tuple[str, ...]
    unavailable_reason: str | None


@dataclass(frozen=True)
class EvidenceDiagnostics:
    observations: tuple[ObservationDiagnostic, ...]
    unknown_reasons: tuple[tuple[str, tuple[str, ...]], ...]
    unexamined_urls: tuple[tuple[str, str], ...]


def diagnose_evidence(discovery, findings, expected_urls=()):
    """Do not infer undiscovered URLs; callers may supply an explicit expected trail."""
    observations = tuple(ObservationDiagnostic(
        i, o.canonical_url, o.availability,
        len(o.document.text) if o.document else 0,
        tuple(sorted(IMPLEMENTED_CHECKS)) if o.availability == 'available' else (),
        None if o.availability == 'available' else 'evidence_unavailable_to_evaluator',
    ) for i, o in enumerate(discovery.observations))
    reasons = {o.availability for o in observations if o.availability != 'available'}
    if any(o.availability == 'available' for o in observations):
        reasons.add('evidence_examined_not_recognized')
    if len(discovery.observations) >= MAX_FETCHES and discovery.pending_urls:
        reasons.add('budget_exhausted')
    attempted = {url for o in discovery.observations for url in (o.requested_url, o.final_url) if url}
    pending = set(discovery.pending_urls)
    unexamined = tuple((url, 'budget_exhausted' if len(discovery.observations) >= MAX_FETCHES
                       else 'candidate_not_fetched') for url in sorted(pending - attempted))
    unexamined += tuple((url, 'url_not_discovered') for url in expected_urls if url not in attempted | pending)
    return EvidenceDiagnostics(observations,
        tuple((f.id, tuple(sorted(reasons))) for f in findings if f.state == 'unknown'), unexamined)
