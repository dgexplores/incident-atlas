import json
import subprocess
from unittest.mock import Mock

from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest

from atlas.app import app
from atlas.collector import collect, parse_stats
from atlas.telemetry import TelemetryBatch, analyze_telemetry
from atlas.triage import explain


def batch():
    return {"source": "unit-test measurements", "baseline_points": 20, "points": [
        {"service": "payments", "metric": "cpu_pct", "minute": i, "value": 25 if i < 20 else 95}
        for i in range(30)]}


def test_real_shaped_data_and_arbitrary_service_hypothesis():
    result = analyze_telemetry(TelemetryBatch.model_validate(batch()))
    assert len(result["incidents"]) == 1
    assert result["findings"][0]["start_minute"] == 20
    assert result["incidents"][0]["title"].startswith("payments CPU pressure")
    assert result["chart_metric"] == "cpu_pct"


@pytest.mark.parametrize("mutate", [
    lambda b: b["points"].append(b["points"][0]),
    lambda b: b["points"].pop(0),
    lambda b: b["points"][0].update(value=float("nan")),
    lambda b: b.update(dependencies={"unknown": ["payments"]}),
    lambda b: b["points"][0].update(metric="shell_command"),
])
def test_invalid_streams_rejected(mutate):
    payload = batch()
    mutate(payload)
    with pytest.raises(ValidationError):
        TelemetryBatch.model_validate(payload)


def test_docker_cpu_can_exceed_one_core():
    rows = parse_stats('{"Name":"worker","CPUPerc":"240.1%","MemPerc":"12.5%"}', 3)
    assert rows[0]["value"] == 240.1
    assert rows[1]["metric"] == "memory_pct"
    for bad in ["NaN%", "-1%", "100.1%"]:
        with pytest.raises(ValueError):
            parse_stats(json.dumps({"Name": "worker", "CPUPerc": "1%", "MemPerc": bad}), 0)


def test_collector_has_no_shell_and_rejects_missing_containers(monkeypatch):
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, '{"Name":"worker","CPUPerc":"1%","MemPerc":"2%"}', ''))
    monkeypatch.setattr("atlas.collector.subprocess.run", runner)
    monkeypatch.setattr("atlas.collector.time.sleep", lambda _: None)
    result = collect(["worker"], 23, 1, 20)
    assert len(result["points"]) == 46
    assert "shell" not in runner.call_args.kwargs
    assert runner.call_args.args[0][-1] == "worker"
    runner.return_value.stdout = ''
    with pytest.raises(ValueError, match="stopped"):
        collect(["worker"], 23, 1, 20)
    with pytest.raises(ValueError):
        collect(["--privileged"], 23, 1, 20)


def test_telemetry_api_persistence_isolation_and_model_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DB_PATH", str(tmp_path / "atlas.db"))
    monkeypatch.delenv("ATLAS_OPERATOR_TOKEN", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/telemetry", json=batch())
        assert response.status_code == 201, response.text
        incident = response.json()["incidents"][0]
        identity = incident["id"]
        assert client.get("/api/workspace").json()["source_kind"] == "user-supplied measurements"
        context = client.get(f"/api/incidents/{identity}/context").json()
        assert context["runbooks"][0]["id"] == "cpu-pressure"
        assert client.post(f"/api/incidents/{identity}/explain").status_code == 503
        monkeypatch.setenv("ATLAS_OPERATOR_TOKEN", "test-operator-token")
        assert client.post(f"/api/incidents/{identity}/explain").status_code == 401
        with TestClient(app) as stranger:
            assert stranger.get(f"/api/incidents/{identity}/context").status_code == 404
        large = b'x' * 1_048_577
        assert client.post('/api/telemetry', content=large).status_code == 413


def test_no_implicit_dependency_graph_merging():
    payload = batch()
    payload["points"] += [{**p, "service": "other"} for p in payload["points"]]
    assert len(analyze_telemetry(TelemetryBatch.model_validate(payload))["incidents"]) == 2
    payload["dependencies"] = {"payments": ["other"]}
    assert len(analyze_telemetry(TelemetryBatch.model_validate(payload))["incidents"]) == 1


def test_model_rejects_unknown_citations_and_does_not_send_secrets(monkeypatch):
    for key, value in {"ATLAS_LLM_BASE_URL": "https://provider.example/v1", "ATLAS_LLM_MODEL": "test-model", "ATLAS_LLM_API_KEY": "test-secret"}.items():
        monkeypatch.setenv(key, value)
    incident = analyze_telemetry(TelemetryBatch.model_validate(batch()))["incidents"][0]
    advice = {"hypothesis": "CPU pressure may be involved.", "evidence_ids": [incident["evidence"][0]["id"]], "runbook_ids": ["cpu-pressure"], "next_checks": ["Inspect workload and CPU limits."]}
    def responder(request):
        assert "test-secret" not in request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(advice)}}]})
    original = httpx.Client
    monkeypatch.setattr("atlas.triage.httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(responder), **kwargs))
    assert explain(incident)["runbook_ids"] == ["cpu-pressure"]
    advice["evidence_ids"] = ["fabricated-finding"]
    with pytest.raises(ValueError, match="unknown"):
        explain(incident)


def test_stable_multicore_cpu_is_not_a_false_incident():
    payload = batch()
    for point in payload["points"]:
        point["value"] = 240.0
    assert analyze_telemetry(TelemetryBatch.model_validate(payload))["findings"] == []
