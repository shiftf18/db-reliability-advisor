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
        # Check for connection pressure scenario (Scenario B)
        if "connection_utilization_percent" in by_name:
            return self._analyze_connection_pressure(by_name)

        # Check for query regression scenario (Scenario A)
        if "documents_examined" in by_name:
            return self._analyze_query_regression(by_name)

        # Check for latency-only scenario
        if "request_p95_ms" in by_name:
            finding = self._create_latency_finding(by_name["request_p95_ms"], "D1")
            return [finding] if finding else []

        return []

    @staticmethod
    def _comparison(evidence: Evidence) -> dict[str, Any] | None:
        """Extract comparison dict from evidence value."""
        if (
            evidence.kind != "metric_comparison"
            and evidence.kind != "query_comparison"
            and evidence.kind != "query_plan"
        ):
            return None
        if not isinstance(evidence.value, dict):
            return None
        if "before" not in evidence.value or "after" not in evidence.value:
            return None
        return evidence.value

    def _create_latency_finding(
        self, latency: Evidence, finding_id: str
    ) -> DeterministicFinding | None:
        """Create a latency regression finding from metric comparison evidence."""
        value = self._comparison(latency)
        if value is None:
            return None
        try:
            before = float(value["before"])
            after = float(value["after"])
        except (TypeError, ValueError):
            return None
        if before <= 0:
            return None

        increase = ((after - before) / before) * 100
        threshold = self._settings.latency_regression_threshold_percent
        if increase < threshold:
            return None

        return DeterministicFinding(
            id=finding_id,
            rule="latency_regression",
            result={
                "increasePercent": round(increase),
                "beforeMs": before,
                "afterMs": after,
                "thresholdPercent": threshold,
            },
            evidence_ids=[latency.id],
        )

    def _analyze_query_regression(self, items: dict[str, Evidence]) -> list[DeterministicFinding]:
        """
        Analyze query regression scenario (Scenario A).

        Rules:
        1. Latency regression (request_p95_ms)
        2. Scan efficiency regression (documents_examined / documents_returned)
        3. Query plan change (query_plan)
        """
        required = {"documents_examined", "documents_returned", "query_plan", "request_p95_ms"}
        if not required.issubset(items):
            finding = None
            if "request_p95_ms" in items:
                finding = self._create_latency_finding(items["request_p95_ms"], "D1")
            return [finding] if finding else []

        examined = items["documents_examined"]
        returned = items["documents_returned"]
        plan = items["query_plan"]
        latency = items["request_p95_ms"]

        examined_value = self._comparison(examined)
        returned_value = self._comparison(returned)
        plan_value = self._comparison(plan)
        if examined_value is None or returned_value is None or plan_value is None:
            finding = self._create_latency_finding(latency, "D1")
            return [finding] if finding else []

        findings: list[DeterministicFinding] = []

        # Rule 1: Latency Regression
        latency_finding = self._create_latency_finding(latency, "D1")
        if latency_finding:
            findings.append(latency_finding)

        # Rule 2: Scan Efficiency Regression
        try:
            before_returned_raw = float(returned_value["before"])
            after_returned_raw = float(returned_value["after"])
            before_returned = max(before_returned_raw, 1)
            after_returned = max(after_returned_raw, 1)
            before_examined = float(examined_value["before"])
            after_examined = float(examined_value["after"])
            before_ratio = before_examined / before_returned
            after_ratio = after_examined / after_returned
            increase_percent = ((after_ratio - before_ratio) / max(abs(before_ratio), 1)) * 100
            if increase_percent >= self._settings.scan_efficiency_change_threshold_percent:
                multiplier = after_ratio / before_ratio if before_ratio > 0 else None
                findings.append(
                    DeterministicFinding(
                        id=f"D{len(findings) + 1}",
                        rule="scan_efficiency_regression",
                        result={
                            "beforeRatio": round(before_ratio, 2),
                            "afterRatio": round(after_ratio, 2),
                            "multiplier": round(multiplier, 2) if multiplier is not None else None,
                        },
                        evidence_ids=[examined.id, returned.id],
                    )
                )
        except (TypeError, ValueError, ZeroDivisionError):
            pass

        # Rule 3: Query Plan Change
        if plan_value.get("before") != plan_value.get("after"):
            findings.append(
                DeterministicFinding(
                    id=f"D{len(findings) + 1}",
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
        self, items: dict[str, Evidence]
    ) -> list[DeterministicFinding]:
        """
        Analyze connection pressure scenario (Scenario B).

        Rules:
        1. Connection pressure (connection_utilization_percent + connection_failures)
        2. Latency regression (request_p95_ms)
        3. Query plan stability (query_plan + scan_ratio) - contradicting evidence
        """
        findings: list[DeterministicFinding] = []
        pressure = None
        if "connection_utilization_percent" in items:
            pressure = self._create_connection_pressure_finding(
                items["connection_utilization_percent"],
                items.get("connection_failures"),
                items.get("request_p95_ms"),
                items.get("request_error_rate_percent") or items.get("error_rate"),
                "D1",
            )
        if pressure:
            findings.append(pressure)

        # Rule 2: Latency Regression
        if "request_p95_ms" in items:
            latency_finding = self._create_latency_finding(
                items["request_p95_ms"], f"D{len(findings) + 1}"
            )
            if latency_finding:
                findings.append(latency_finding)

        # Rule 3: Query Plan Stability (contradicting evidence)
        plan = items.get("query_plan")
        ratio = items.get("scan_ratio")
        if plan:
            plan_value = self._comparison(plan)
            window_plan = plan.value if isinstance(plan.value, dict) else {}
            plan_is_stable = (
                plan_value is not None and plan_value["before"] == plan_value["after"]
            ) or window_plan.get("stable") is True
            if plan_is_stable:
                result: dict[str, Any] = {
                    "plan": plan_value["after"] if plan_value else window_plan.get("observed")
                }
                evidence_ids = [plan.id]
                if ratio:
                    ratio_value = self._comparison(ratio)
                    if ratio_value is not None:
                        try:
                            before_ratio = float(ratio_value["before"])
                            after_ratio = float(ratio_value["after"])
                            change_percent = (
                                (after_ratio - before_ratio) / max(abs(before_ratio), 1)
                            ) * 100
                        except (TypeError, ValueError):
                            change_percent = None
                        if (
                            change_percent is not None
                            and abs(change_percent)
                            <= self._settings.scan_efficiency_change_threshold_percent
                        ):
                            result["scanRatioChangePercent"] = round(change_percent)
                            evidence_ids.append(ratio.id)
                    else:
                        scan_ratio = self._numeric_value(ratio)
                        if scan_ratio is not None:
                            result["scanRatio"] = scan_ratio
                            evidence_ids.append(ratio.id)
                findings.append(
                    DeterministicFinding(
                        id=f"D{len(findings) + 1}",
                        rule="query_plan_stable",
                        result=result,
                        evidence_ids=evidence_ids,
                    )
                )

        return findings

    def _create_connection_pressure_finding(
        self,
        connections: Evidence,
        failures: Evidence | None,
        request_latency: Evidence | None,
        error_rate: Evidence | None,
        finding_id: str,
    ) -> DeterministicFinding | None:
        """Create a pressure finding when utilization is high or failures occurred."""
        connection_value = self._comparison(connections)
        after = (
            self._numeric_value(connections)
            if connection_value is None
            else self._numeric_value(connections, "after")
        )
        if after is None:
            return None
        before = self._numeric_value(connections, "before") if connection_value else None

        failure_value = failures.value if failures else 0
        if isinstance(failure_value, dict):
            failure_count = failure_value.get("count", 0)
        elif isinstance(failure_value, (int, float)):
            failure_count = failure_value
        else:
            failure_count = 0
        try:
            failure_count = max(int(failure_count), 0)
        except (TypeError, ValueError):
            failure_count = 0

        threshold = self._settings.connection_pressure_threshold_percent
        if after < threshold and failure_count == 0:
            return None

        evidence_ids = [connections.id]
        if failures is not None:
            evidence_ids.append(failures.id)
        result: dict[str, Any] = {
            "utilizationPercent": after,
            "failureCount": failure_count,
            "thresholdPercent": threshold,
        }
        if before is not None:
            result["beforePercent"] = before
            result["afterPercent"] = after
        if request_latency is not None:
            latency = self._numeric_value(request_latency)
            if latency is not None:
                result["requestP95Ms"] = latency
                evidence_ids.append(request_latency.id)
        if error_rate is not None:
            rate = self._numeric_value(error_rate)
            if rate is not None:
                result[
                    "errorRatePercent"
                    if error_rate.name == "request_error_rate_percent"
                    else "errorRateRatio"
                ] = rate
                evidence_ids.append(error_rate.id)

        return DeterministicFinding(
            id=finding_id,
            rule="connection_pressure",
            result=result,
            evidence_ids=evidence_ids,
        )

    @classmethod
    def _numeric_value(cls, evidence: Evidence, key: str = "after") -> float | None:
        comparison = cls._comparison(evidence)
        if comparison is not None:
            value: Any = comparison.get(key)
        else:
            value = evidence.value
            if isinstance(value, dict):
                value = value.get("median", value.get("value"))
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
