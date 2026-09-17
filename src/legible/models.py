"""Shared result consumed by file and browser presentations."""
from dataclasses import dataclass

from legible.analyze.classification import SurfaceClassification
from legible.analyze.models import Finding
from legible.discover.surfaces import DiscoveryResult
from legible.fetch.models import FetchObservation


@dataclass(frozen=True)
class ScanReport:
    homepage: FetchObservation
    discovery: DiscoveryResult
    classification: SurfaceClassification
    findings: list[Finding]
    fixes: list[str]
