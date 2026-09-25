from datetime import UTC, datetime

import httpx

from services.analysis_service.app.adapters.base import CollectedEvidence
from services.analysis_service.app.adapters.loki import LokiAdapter
from services.analysis_service.app.adapters.multi_source import MultiSourceAdapter
from services.analysis_service.app.adapters.prometheus import PrometheusAdapter
from services.analysis_service.app.contracts.models import AnalysisRequest


def make_request() -> AnalysisRequest:
    return AnalysisRequest(
        target="orders-api",
        start_time=datetime(2026, 9, 20, 10, tzinfo=UTC),
        end_time=datetime(2026, 9, 20, 10, 10, tzinfo=UTC),
    )


def test_prometheus_collects_project_metrics_and_normalizes_values(monkeypatch) -> None:
    queries = []

    def fake_get(url, params, timeout):
        query = params["query"]
        queries.append(query)
        value = "0.25" if "histogram_quantile" in query else "0.125"
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"status": "success", "data": {"result": [{"value": ["1", value]}]}},
        )

    monkeypatch.setattr("services.analysis_service.app.adapters.prometheus.httpx.get", fake_get)
    collected = PrometheusAdapter("http://prometheus").collect(make_request())

    assert len(collected.evidence) == 2
    assert collected.evidence[0].name == "request_p95_ms"
    assert collected.evidence[0].value == 250
    assert collected.evidence[0].unit == "ms"
    assert collected.evidence[1].name == "error_rate"
    assert collected.evidence[1].value == 0.125
    assert collected.evidence[1].unit == "ratio"
    assert all(item.source.system == "prometheus" for item in collected.evidence)
    assert [item.source.query for item in collected.evidence] == queries
    assert all("orders_api_" in query and 'job="orders-api"' in query for query in queries)
    assert "/ clamp_min(" in queries[1]


def test_prometheus_records_unavailability_without_raising(monkeypatch) -> None:
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("Prometheus is unavailable")

    monkeypatch.setattr("services.analysis_service.app.adapters.prometheus.httpx.get", unavailable)
    collected = PrometheusAdapter("http://prometheus").collect(make_request())

    assert collected.evidence == []
    assert len(collected.missing_evidence) == 2
    assert all("Failed to collect" in item for item in collected.missing_evidence)


def test_loki_uses_valid_queries_and_preserves_sanitized_provenance(monkeypatch) -> None:
    queries = []
    timestamp_ns = str(int(datetime(2026, 9, 20, 10, 5, tzinfo=UTC).timestamp() * 1_000_000_000))
    response_data = {
        "status": "success",
        "data": {
            "result": [
                {
                    "stream": {},
                    "values": [
                        [
                            timestamp_ns,
                            '{"event":"deployment","service":"orders-api",'
                            '"message":"email=person@example.com"}',
                        ]
                    ],
                }
            ]
        },
    }

    def fake_get(url, params, timeout):
        queries.append(params["query"])
        return httpx.Response(200, request=httpx.Request("GET", url), json=response_data)

    monkeypatch.setattr("services.analysis_service.app.adapters.loki.httpx.get", fake_get)
    collected = LokiAdapter("http://loki").collect(make_request())

    assert len(collected.evidence) == 2
    assert all(item.source.system == "loki" for item in collected.evidence)
    assert [item.source.query for item in collected.evidence] == queries
    assert queries[0] == '{service="mongodb",source="diagnostic-log"} | json'
    assert "event=~" in queries[1]
    assert all(", namespace" not in query for query in queries)
    assert collected.evidence[0].value["message"] == "email=[REDACTED]"


def test_multi_source_collection_preserves_partial_failures() -> None:
    class AvailableSource:
        def collect(self, request, fixture_name=None):
            return CollectedEvidence(evidence=[], missing_evidence=["No source data"])

    class FailedSource:
        def collect(self, request, fixture_name=None):
            raise RuntimeError("source unavailable")

    collected = MultiSourceAdapter([AvailableSource(), FailedSource()]).collect(make_request())

    assert collected.evidence == []
    assert "No source data" in collected.missing_evidence
    assert any("FailedSource" in item for item in collected.missing_evidence)
