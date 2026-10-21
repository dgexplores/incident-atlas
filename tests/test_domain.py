from atlas.domain import Observation, analyze, correlate, detect, generate


def test_healthy_holdout_seeds_remain_quiet():
    # Seeds used by tests differ from the showcased seed. This still only
    # measures this synthetic distribution, not field false-positive rates.
    for seed in range(1000, 1020):
        assert analyze("healthy", seed)["incidents"] == []


def test_fault_scenarios_find_expected_service_evidence():
    for seed in range(1000, 1006):
        pressure = analyze("database-pressure", seed)
        assert len(pressure["incidents"]) == 1
        incident = pressure["incidents"][0]
        assert incident["severity"] == "critical"
        assert set(incident["services"]) == {"orders-db", "checkout-api", "edge-gateway"}
        assert any(item["metric"] == "pool_pct" for item in incident["evidence"])
        assert "may" in incident["title"]
        ids = {item["id"] for item in incident["evidence"]}
        assert all(set(hypothesis["basis"]) <= ids for hypothesis in incident["hypotheses"])
        assert len(analyze("independent-faults", seed)["incidents"]) == 2
        memory = analyze("memory-growth", seed)["incidents"]
        assert len(memory) == 1 and memory[0]["services"] == ["checkout-api"]


def test_one_point_spike_is_not_an_incident():
    rows = generate("healthy", 2000)
    rows = [Observation(row.service, row.metric, row.minute, 1000 if row.service == "orders-db" and row.metric == "latency_ms" and row.minute == 70 else row.value) for row in rows]
    assert detect(rows) == []


def test_detection_is_independent_of_input_order():
    rows = generate("database-pressure", 12)
    assert detect(rows) == detect(list(reversed(rows)))


def test_anomalies_outside_overlap_window_remain_separate():
    item = {"id": "a", "service": "orders-db", "metric": "latency_ms", "start_minute": 60, "end_minute": 65, "peak": 400}
    other = {**item, "id": "b", "start_minute": 80, "end_minute": 90}
    assert len(correlate([item, other])) == 2
