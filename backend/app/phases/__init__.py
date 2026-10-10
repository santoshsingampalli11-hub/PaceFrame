"""Experimental BFC/FFC candidate search. Not validated contact detection.

Release detection is not included. Results are not written into manual
annotation files.
"""

from app.phases.contact_candidates import (
    ContactCandidate,
    ContactHeuristicConfig,
    ContactSearchResult,
    FootSettlement,
    search_contact_candidates,
)
from app.phases.reference_comparison import (
    ComparisonSummary,
    ReferenceFrameComparison,
    compare_reference_frame,
    summarise_comparisons,
)

__all__ = [
    "ComparisonSummary",
    "ContactCandidate",
    "ContactHeuristicConfig",
    "ContactSearchResult",
    "FootSettlement",
    "ReferenceFrameComparison",
    "compare_reference_frame",
    "search_contact_candidates",
    "summarise_comparisons",
]
