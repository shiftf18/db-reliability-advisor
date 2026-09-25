import math
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from ..contracts.models import (
    AnalysisRequest,
    Evidence,
    EvidenceObservationWindow,
    EvidenceSource,
)
from .base import CollectedEvidence


class PrometheusAdapter:
    """
    Adapter for collecting metrics from Prometheus.
    Implements: Fetch and normalize Prometheus metrics (request p95, error rate).
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def ready(self) -> bool:
        """Check if Prometheus is ready."""
        try:
            response = httpx.get(f"{self.base_url}/-/ready", timeout=2)
            return response.is_success
        except httpx.RequestError:
            return False

    def collect(
        self, request: AnalysisRequest, fixture_name: str | None = None
    ) -> CollectedEvidence:
        """
        Collect request p95 latency and error rate from Prometheus.
        Returns CollectedEvidence with list of Evidence objects.
        """
        evidence_list = []
        missing_evidence = []

        # If fixture_name is provided, we could load mock data for testing.
        # For simplicity, we skip fixture loading in this implementation.
        # In a real test environment, you would load from fixture files.
        # mock mode uses MockAdapter instead
        if fixture_name:
            # For now, return empty evidence when fixture mode is requested.
            # This allows tests to proceed without actual Prometheus.
            return CollectedEvidence(evidence=[], missing_evidence=[])

        target = request.target
        escaped_target = target.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        window_queries = {
            "request_p95_ms": (
                "histogram_quantile(0.95, "
                "sum by (le) (rate(orders_api_request_duration_seconds_bucket"
                f'{{job="{escaped_target}"}}[5m])))'
            ),
            "request_error_rate_percent": (
                "(sum(rate(orders_api_requests_total"
                f'{{job="{escaped_target}",status=~"5.."}}[5m])) or vector(0)) '
                "/ clamp_min(sum(rate(orders_api_requests_total"
                f'{{job="{escaped_target}"}}[5m])), 1e-12)'
            ),
            "connection_utilization_percent": (
                '100 * sum(mongodb_ss_connections{job="mongodb-exporter",conn_type="current"}) '
                '/ clamp_min(sum(mongodb_ss_connections{job="mongodb-exporter",'
                'conn_type="current"}) + '
                'sum(mongodb_ss_connections{job="mongodb-exporter",conn_type="available"}), 1)'
            ),
        }
        duration_seconds = max(int((request.end_time - request.start_time).total_seconds()), 1)
        step_seconds = max(15, math.ceil(duration_seconds / 240))

        for metric_name, promql in window_queries.items():
            try:
                response = httpx.get(
                    f"{self.base_url}/api/v1/query_range",
                    params={
                        "query": promql,
                        "start": request.start_time.timestamp(),
                        "end": request.end_time.timestamp(),
                        "step": step_seconds,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                if data["status"] != "success":
                    raise ValueError(f"Prometheus query failed: {data}")

                result = data["data"]["result"]
                if not result:
                    # No data returned for this metric.
                    missing_evidence.append(f"No data for {metric_name}")
                    continue

                samples = []
                for series in result:
                    for timestamp, value_str in series.get("values", []):
                        value = float(value_str)
                        if not math.isfinite(value):
                            continue
                        if metric_name == "request_p95_ms":
                            value *= 1000.0
                        elif metric_name == "request_error_rate_percent":
                            value *= 100.0
                        samples.append(
                            {
                                "timestamp": datetime.fromtimestamp(float(timestamp), UTC),
                                "value": value,
                            }
                        )
                if not samples:
                    missing_evidence.append(f"No samples for {metric_name}")
                    continue
                samples.sort(key=lambda sample: sample["timestamp"])
                unit = (
                    "ms"
                    if metric_name == "request_p95_ms"
                    else (
                        "percent"
                        if metric_name
                        in {"request_error_rate_percent", "connection_utilization_percent"}
                        else "ratio"
                    )
                )

                evidence = Evidence(
                    id=str(uuid4()),
                    kind="metric_window",
                    name=metric_name,
                    value={"samples": samples},
                    unit=unit,
                    source=EvidenceSource(system="prometheus", query=promql),
                    observation_window=EvidenceObservationWindow(
                        start_time=request.start_time,
                        end_time=request.end_time,
                    ),
                    timestamp=None,  # We rely on observation_window for the time range.
                )
                evidence_list.append(evidence)

            except (httpx.RequestError, ValueError, KeyError, IndexError) as exc:
                # Record failure for this metric.
                missing_evidence.append(f"Failed to collect {metric_name} from Prometheus: {exc}")
                continue

        failure_query = (
            "increase(mongodb_ss_metrics_operation_numConnectionNetworkTimeouts"
            f'{{job="mongodb-exporter"}}[{duration_seconds}s])'
        )
        try:
            response = httpx.get(
                f"{self.base_url}/api/v1/query",
                params={"query": failure_query, "time": request.end_time.timestamp()},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if data["status"] != "success":
                raise ValueError(f"Prometheus query failed: {data}")
            result = data["data"]["result"]
            if not result:
                missing_evidence.append("No data for connection_failures")
            else:
                failure_count = float(result[0]["value"][1])
                if not math.isfinite(failure_count):
                    raise ValueError(f"Non-finite value from Prometheus: {failure_count}")
                evidence_list.append(
                    Evidence(
                        id=str(uuid4()),
                        kind="metric_window",
                        name="connection_failures",
                        value=max(round(failure_count), 0),
                        unit="count",
                        source=EvidenceSource(system="prometheus", query=failure_query),
                        observation_window=EvidenceObservationWindow(
                            start_time=request.start_time,
                            end_time=request.end_time,
                        ),
                    )
                )
        except (httpx.RequestError, ValueError, KeyError, IndexError) as exc:
            missing_evidence.append(f"Failed to collect connection_failures from Prometheus: {exc}")

        return CollectedEvidence(
            evidence=evidence_list,
            missing_evidence=missing_evidence,
        )
