import json
from datetime import UTC, datetime

import httpx

from services.analysis_service.app.adapters.base import CollectedEvidence
from services.analysis_service.app.adapters.loki import LokiAdapter
from services.analysis_service.app.adapters.mongodb import MongoMetadataAdapter
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
    request = make_request()

    def fake_get(url, params, timeout):
        query = params["query"]
        queries.append(query)
        if url.endswith("query_range"):
            if "histogram_quantile" in query:
                values = [[str(params["start"]), "0.2"], [str(params["end"]), "0.4"]]
            elif "orders_api_requests_total" in query:
                values = [[str(params["start"]), "0.01"], [str(params["end"]), "0.03"]]
            else:
                values = [[str(params["start"]), "25"], [str(params["end"]), "92"]]
            result = [{"values": values}]
        else:
            result = [{"value": [str(params["time"]), "2"]}]
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"status": "success", "data": {"result": result}},
        )

    monkeypatch.setattr("services.analysis_service.app.adapters.prometheus.httpx.get", fake_get)
    collected = PrometheusAdapter("http://prometheus").collect(request)

    assert len(collected.evidence) == 4
    assert collected.evidence[0].name == "request_p95_ms"
    assert collected.evidence[0].value["samples"][0]["value"] == 200
    assert collected.evidence[0].value["samples"][1]["value"] == 400
    assert collected.evidence[0].unit == "ms"
    assert collected.evidence[1].name == "request_error_rate_percent"
    assert collected.evidence[1].value["samples"][0]["value"] == 1
    assert collected.evidence[1].unit == "percent"
    assert collected.evidence[2].name == "connection_utilization_percent"
    assert collected.evidence[2].value["samples"][1]["value"] == 92
    assert collected.evidence[3].name == "connection_failures"
    assert collected.evidence[3].value == 2
    assert all(item.source.system == "prometheus" for item in collected.evidence)
    assert all("orders_api_" in query and 'job="orders-api"' in query for query in queries[:2])
    assert any("mongodb_ss_connections" in query for query in queries)
    assert any("numConnectionNetworkTimeouts" in query for query in queries)
    assert all(item.source.query for item in collected.evidence)
    assert all(
        item.observation_window.start_time == request.start_time for item in collected.evidence
    )


def test_prometheus_records_unavailability_without_raising(monkeypatch) -> None:
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("Prometheus is unavailable")

    monkeypatch.setattr("services.analysis_service.app.adapters.prometheus.httpx.get", unavailable)
    collected = PrometheusAdapter("http://prometheus").collect(make_request())

    assert collected.evidence == []
    assert len(collected.missing_evidence) == 4
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


def test_loki_extracts_allowlisted_mongodb_slow_operation_fields(monkeypatch) -> None:
    timestamp_ns = str(int(datetime(2026, 9, 20, 10, 5, tzinfo=UTC).timestamp() * 1_000_000_000))
    slow_log = {
        "msg": "Slow query",
        "attr": {
            "type": "command",
            "ns": "reliability_demo.orders",
            "command": {"find": "orders", "filter": {"customerId": "private-value"}},
            "durationMillis": 120,
            "docsExamined": 200000,
            "nreturned": 50,
            "keysExamined": 0,
            "planSummary": "COLLSCAN",
        },
    }

    def fake_get(url, params, timeout):
        result = (
            [{"stream": {}, "values": [[timestamp_ns, json.dumps(slow_log)]]}]
            if "diagnostic-log" in params["query"]
            else []
        )
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"status": "success", "data": {"result": result}},
        )

    monkeypatch.setattr("services.analysis_service.app.adapters.loki.httpx.get", fake_get)
    collected = LokiAdapter("http://loki").collect(make_request())

    assert len(collected.evidence) == 1
    assert collected.evidence[0].value == {
        "namespace": "reliability_demo.orders",
        "operation": "find",
        "durationMs": 120,
        "documentsExamined": 200000,
        "documentsReturned": 50,
        "keysExamined": 0,
        "planSummary": "COLLSCAN",
    }
    assert "private-value" not in str(collected.evidence[0].value)
    assert LokiAdapter._normalize_slow_operation(
        {"msg": "Slow query", "attr": {"command": {"find": "orders", "filter": {"id": "private"}}}}
    ) == {"message": "Slow query"}


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


def test_mongodb_collects_read_only_metadata_with_supported_index_api(monkeypatch) -> None:
    calls = []

    class FakeCollection:
        def list_indexes(self):
            calls.append("list_indexes")
            return [{"name": "_id_", "key": {"_id": 1}}]

    class FakeDatabase:
        def __getitem__(self, name):
            assert name == "orders"
            return FakeCollection()

        def command(self, command_name):
            calls.append(command_name)
            if command_name == "serverStatus":
                return {"connections": {"current": 4, "available": 100}}
            return {"version": "8.0.32"}

    class FakeClient:
        def __init__(self, uri):
            self.uri = uri
            self.admin = FakeDatabase()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get_default_database(self):
            return FakeDatabase()

    monkeypatch.setattr("services.analysis_service.app.adapters.mongodb.MongoClient", FakeClient)
    collected = MongoMetadataAdapter("mongodb://test/reliability_demo").collect(make_request())

    assert [item.name for item in collected.evidence] == ["indexes", "connection_limit", "version"]
    assert calls == ["list_indexes", "serverStatus", "buildInfo"]
    assert all(item.source.system == "mongodb" for item in collected.evidence)
    assert collected.missing_evidence == []
