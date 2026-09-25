"""
Raw Evidence Processor for DBADV-02.

Handles the full evidence building pipeline for raw adapter output
from Prometheus, Loki, and MongoDB adapters.
"""

from __future__ import annotations

from ...adapters.base import CollectedEvidence
from ...contracts.models import (
    AnalysisPackage,
    AnalysisRequest,
    AnalysisWindow,
)
from ..normalizer import (
    normalize_evidence_list,
)
from .bounder import bound_evidence
from .deduplicator import deduplicate_evidence
from .event_discovery import discover_context_events
from .evidence_kinds import build_evidence_kinds
from .filter import filter_evidence
from .id_generator import assign_sequential_ids
from .missing_tracker import track_missing_evidence
from .sanitizer import sanitize_value
from .time_aligner import time_align_evidence


class RawEvidenceProcessor:
    """
    Processes raw adapter evidence through the full pipeline.

    Pipeline stages:
    1. Normalize raw evidence using the normalization layer
    2. Time-align evidence to the requested window
    3. Discover context events (deployments, restarts, etc.)
    4. Sanitize sensitive data
    5. Filter irrelevant records
    6. Deduplicate repeated entries
    7. Construct evidence kinds (metric_comparison, query_comparison, etc.)
    8. Generate sequential evidence IDs (E1, E2, ...)
    9. Track missing evidence
    10. Bound the evidence list size
    """

    # Maximum number of evidence items to prevent unbounded growth
    MAX_EVIDENCE_ITEMS = 50

    # Expected evidence names for each scenario type
    QUERY_REGRESSION_EVIDENCE = {
        "request_p95_ms",
        "documents_examined",
        "documents_returned",
        "query_plan",
    }

    CONNECTION_PRESSURE_EVIDENCE = {
        "connection_utilization_percent",
        "connection_failures",
        "request_p95_ms",
        "request_error_rate_percent",
        "query_plan",
        "scan_ratio",
    }

    def build(
        self,
        analysis_id: str,
        request: AnalysisRequest,
        collected: CollectedEvidence,
    ) -> AnalysisPackage:
        """
        Build an AnalysisPackage from raw collected evidence.

        Args:
            analysis_id: Unique identifier for this analysis
            request: The analysis request containing target and time window
            collected: Raw evidence collected from all adapters

        Returns:
            AnalysisPackage with structured evidence ready for deterministic analysis
        """
        # Stage 1: Normalize raw evidence using the normalization layer
        normalized_metrics, normalized_logs, normalized_metadata = normalize_evidence_list(
            collected.evidence
        )

        # Stage 2: Time-align all evidence to the requested window
        aligned_metrics = time_align_evidence(normalized_metrics, request)
        aligned_logs = time_align_evidence(normalized_logs, request)
        aligned_metadata = time_align_evidence(normalized_metadata, request)

        # Stage 3: Discover context events from logs
        context_events = discover_context_events(aligned_logs, request)

        # Stage 4: Sanitize all evidence (double-check after adapters)
        sanitized_metrics = [sanitize_value(m) for m in aligned_metrics]
        sanitized_logs = [sanitize_value(log) for log in aligned_logs]
        sanitized_metadata = [sanitize_value(m) for m in aligned_metadata]
        sanitized_events = [sanitize_value(e) for e in context_events]

        # Stage 5: Filter irrelevant records
        filtered_metrics = filter_evidence(sanitized_metrics, request)
        filtered_logs = filter_evidence(sanitized_logs, request)
        filtered_metadata = filter_evidence(sanitized_metadata, request)
        filtered_events = filter_evidence(sanitized_events, request)

        # Stage 6: Deduplicate repeated entries
        deduped_metrics = deduplicate_evidence(filtered_metrics)
        deduped_logs = deduplicate_evidence(filtered_logs)
        deduped_metadata = deduplicate_evidence(filtered_metadata)
        deduped_events = deduplicate_evidence(filtered_events)

        # Stage 7: Construct evidence kinds for deterministic analysis
        evidence_items = build_evidence_kinds(
            deduped_metrics,
            deduped_logs,
            deduped_metadata,
            deduped_events,
            request,
        )

        # Stage 8: Generate sequential evidence IDs (E1, E2, ...)
        evidence_items = assign_sequential_ids(evidence_items)

        # Stage 9: Track missing evidence
        missing_evidence = track_missing_evidence(
            evidence_items,
            collected.missing_evidence,
            request,
            self.QUERY_REGRESSION_EVIDENCE,
            self.CONNECTION_PRESSURE_EVIDENCE,
        )

        # Stage 10: Bound evidence size
        bounded_evidence = bound_evidence(evidence_items, self.MAX_EVIDENCE_ITEMS)

        return AnalysisPackage(
            analysis_id=analysis_id,
            target=request.target,
            window=AnalysisWindow(start_time=request.start_time, end_time=request.end_time),
            evidence=bounded_evidence,
            deterministic_findings=[],
            missing_evidence=missing_evidence,
        )
