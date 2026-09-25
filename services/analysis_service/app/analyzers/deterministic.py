from typing import Any

from ..config import get_settings
from ..contracts.models import DeterministicFinding, Evidence


class DeterministicAnalyzer:
    """
    Deterministic analysis rules that calculate reproducible facts from evidence.

    All rules operate purely on evidence values - no external data or AI involved.
    Thresholds are configurable via environment variables.
    """

    RULE_VERSION = "1.0.0"

    def __init__(self) -> None:
        self._settings = get_settings()

    def analyze(self, evidence: list[Evidence]) -> list[DeterministicFinding]:
        """
        Analyze evidence and return deterministic findings.

        Args:
            evidence: List of evidence items from the evidence builder

        Returns:
            List of deterministic findings with rule names, results, and evidence IDs
        """
        if not evidence:
            return []

        by_name = {item.name: item for item in evidence}
        findings: list[DeterministicFinding] = []
        finding_counter = 1

        # Check for connection pressure scenario (Scenario B)
        if "connection_utilization_percent" in by_name:
            findings.extend(self._analyze_connection_pressure(by_name, finding_counter))
            return findings

        # Check for query regression scenario (Scenario A)
        if "documents_examined" in by_name:
            findings.extend(self._analyze_query_regression(by_name, finding_counter))
            return findings

        # Check for latency-only scenario
        if "request_p95_ms" in by_name:
            findings.append(
                self._create_latency_finding(by_name["request_p95_ms"], f"D{finding_counter}")
            )
            return findings

        return []

    @staticmethod
    def _comparison(evidence: Evidence) -> dict[str, Any]:
        """Extract comparison dict from evidence value."""
        if not isinstance(evidence.value, dict):
            raise ValueError(f"Evidence {evidence.id} must contain a comparison object")
        return evidence.value

    def _create_latency_finding(self, latency: Evidence, finding_id: str) -> DeterministicFinding:
        """Create a latency regression finding from metric comparison evidence."""
        value = self._comparison(latency)
        before = float(value["before"])
        after = float(value["after"])

        # Calculate percent increase, handle division by zero
        increase = None
        if before > 0:
            increase = round(((after - before) / before) * 100)

        return DeterministicFinding(
            id=finding_id,
            rule="latency_percent_change",
            result={
                "percentIncrease": increase,
                "beforeMs": before,
                "afterMs": after,
                "thresholdPercent": self._settings.latency_regression_threshold_percent,
            },
            evidence_ids=[latency.id],
        )

    def _analyze_query_regression(
        self, items: dict[str, Evidence], start_id: int
    ) -> list[DeterministicFinding]:
        """
        Analyze query regression scenario (Scenario A).

        Rules:
        1. Latency regression (request_p95_ms)
        2. Scan efficiency regression (documents_examined / documents_returned)
        3. Query plan change (query_plan)
        """
        required = {"documents_examined", "documents_returned", "query_plan", "request_p95_ms"}
        if not required.issubset(items):
            # Missing required evidence - return what we can
            findings = []
            if "request_p95_ms" in items:
                findings.append(self._create_latency_finding(items["request_p95_ms"], "D1"))
            return findings

        examined = items["documents_examined"]
        returned = items["documents_returned"]
        plan = items["query_plan"]
        latency = items["request_p95_ms"]

        examined_value = self._comparison(examined)
        returned_value = self._comparison(returned)
        plan_value = self._comparison(plan)

        findings: list[DeterministicFinding] = []
        finding_id = start_id

        # Rule 1: Latency Regression
        findings.append(self._create_latency_finding(latency, f"D{finding_id}"))
        finding_id += 1

        # Rule 2: Scan Efficiency Regression
        # scanRatio = documentsExamined / max(documentsReturned, 1)
        if returned_value.get("before") is not None and returned_value.get("after") is not None:
            # Check for zero baseline before applying max()
            before_returned_raw = float(returned_value["before"])
            after_returned_raw = float(returned_value["after"])
            before_returned = max(before_returned_raw, 1)
            after_returned = max(after_returned_raw, 1)
            before_examined = float(examined_value["before"])
            after_examined = float(examined_value["after"])

            before_ratio = before_examined / before_returned
            after_ratio = after_examined / after_returned

            # Skip if baseline is zero (can't calculate meaningful ratio change)
            if before_returned_raw == 0:
                pass  # Don't produce scan_ratio_change finding
            else:
                findings.append(
                    DeterministicFinding(
                        id=f"D{finding_id}",
                        rule="scan_ratio_change",
                        result={
                            "before": round(before_ratio, 2),
                            "after": round(after_ratio, 2),
                        },
                        evidence_ids=[examined.id, returned.id],
                    )
                )
                finding_id += 1

        # Rule 3: Query Plan Change
        findings.append(
            DeterministicFinding(
                id=f"D{finding_id}",
                rule="query_plan_change",
                result={
                    "before": plan_value.get("before"),
                    "after": plan_value.get("after"),
                },
                evidence_ids=[plan.id],
            )
        )

        return findings

    def _analyze_connection_pressure(
        self, items: dict[str, Evidence], start_id: int
    ) -> list[DeterministicFinding]:
        """
        Analyze connection pressure scenario (Scenario B).

        Rules:
        1. Connection pressure (connection_utilization_percent + connection_failures)
        2. Latency regression (request_p95_ms)
        3. Query plan stability (query_plan + scan_ratio) - contradicting evidence
        """
        required = {
            "connection_utilization_percent",
            "connection_failures",
            "query_plan",
            "scan_ratio",
            "request_p95_ms",
        }
        if not required.issubset(items):
            # Missing required evidence - return what we can
            findings = []
            if "request_p95_ms" in items:
                findings.append(self._create_latency_finding(items["request_p95_ms"], "D1"))
            if "connection_utilization_percent" in items and "connection_failures" in items:
                findings.extend(
                    self._create_connection_pressure_finding(
                        items["connection_utilization_percent"], items["connection_failures"], "D1"
                    )
                )
            return findings

        connections = items["connection_utilization_percent"]
        failures = items["connection_failures"]
        plan = items["query_plan"]
        ratio = items["scan_ratio"]
        latency = items["request_p95_ms"]

        plan_value = self._comparison(plan)
        ratio_value = self._comparison(ratio)

        findings: list[DeterministicFinding] = []
        finding_id = start_id

        # Rule 1: Connection Pressure
        # Use configurable threshold
        threshold = self._settings.connection_pressure_threshold_percent
        findings.extend(
            self._create_connection_pressure_finding(
                connections, failures, f"D{finding_id}", threshold
            )
        )
        finding_id += len(
            self._create_connection_pressure_finding(connections, failures, "D1", threshold)
        )

        # Rule 2: Latency Regression
        findings.append(self._create_latency_finding(latency, f"D{finding_id}"))
        finding_id += 1

        # Rule 3: Query Plan Stability (contradicting evidence)
        # Check if plan is stable and scan ratio hasn't changed significantly
        change_percent = None
        if ratio_value.get("before") is not None and ratio_value.get("after") is not None:
            before_ratio = float(ratio_value["before"])
            after_ratio = float(ratio_value["after"])
            if before_ratio > 0:
                change_percent = round(((after_ratio - before_ratio) / before_ratio) * 100)

        findings.append(
            DeterministicFinding(
                id=f"D{finding_id}",
                rule="query_plan_stable",
                result={
                    "plan": plan_value.get("after"),
                    "scanRatioChangePercent": change_percent,
                },
                evidence_ids=[plan.id, ratio.id],
            )
        )

        return findings

    def _create_connection_pressure_finding(
        self,
        connections: Evidence,
        failures: Evidence,
        finding_id: str,
        threshold: float | None = None,
    ) -> list[DeterministicFinding]:
        """Create connection pressure finding."""
        connection_value = self._comparison(connections)

        if threshold is None:
            threshold = self._settings.connection_pressure_threshold_percent

        return [
            DeterministicFinding(
                id=finding_id,
                rule="connection_pressure",
                result={
                    "beforePercent": float(connection_value["before"]),
                    "afterPercent": float(connection_value["after"]),
                    "thresholdPercent": threshold,
                },
                evidence_ids=[connections.id, failures.id],
            )
        ]
