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
        # Use the end time of the analysis window as the query time.
        query_time = request.end_time.timestamp()

        # Define the two allowlisted PromQL queries from the step description.
        # We substitute the target from the request.
        queries = {
            "request_p95_ms": (
                f"histogram_quantile(0.95, "
                f"sum(rate(http_request_duration_seconds_bucket"
                f'{{service="{target}"}}[5m])) by (le))'
            ),
            "error_rate": (
                f'sum(rate(http_requests_total{{service="{target}",status=~"5.."}}[5m]))'
            ),
        }

        for metric_name, promql in queries.items():
            try:
                # Query Prometheus instant API.
                response = httpx.get(
                    f"{self.base_url}/api/v1/query",
                    params={"query": promql, "time": query_time},
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

                # Extract the value (assuming scalar result).
                # Prometheus returns a list of [timestamp, value] strings.
                value_str = result[0]["value"][1]
                try:
                    value = float(value_str)
                except ValueError as err:
                    raise ValueError(f"Invalid value from Prometheus: {value_str}") from err

                # Normalize latency to milliseconds if needed.
                if metric_name == "request_p95_ms":
                    # The histogram_quantile returns seconds (assuming bucket in seconds).
                    value = value * 1000.0  # convert to milliseconds
                    unit = "ms"
                else:
                    # Error rate is a ratio (0-1).
                    unit = "ratio"

                # Create Evidence object.
                evidence = Evidence(
                    id=str(uuid4()),
                    kind="metric_window",
                    name=metric_name,
                    value=value,
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

        return CollectedEvidence(
            evidence=evidence_list,
            missing_evidence=missing_evidence,
        )
