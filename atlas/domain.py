"""Statistical detection and evidence-linked, explicitly heuristic triage.

No LLM or external data source is required. Baselines use only the opening
training window; observations from the incident never update that baseline.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import random
import statistics

SERVICES = ("edge-gateway", "checkout-api", "orders-db", "catalog-api")
METRICS = {
    "latency_ms": (80.0, 8.0, "ms", 300.0),
    "error_pct": (0.15, 0.06, "%", 3.0),
    "cpu_pct": (35.0, 3.0, "%", 85.0),
    "memory_pct": (42.0, 2.0, "%", 85.0),
    "pool_pct": (30.0, 3.0, "%", 85.0),
}
SCENARIOS = {
    "database-pressure": {"title": "Database connection pressure", "summary": "A busy connection pool delays checkout and propagates errors to the edge."},
    "memory-growth": {"title": "Checkout memory growth", "summary": "Memory rises while checkout becomes slower. The evidence supports investigation, not a proven leak."},
    "healthy": {"title": "Healthy baseline", "summary": "Ordinary sensor noise across four services. The detector should stay quiet."},
    "independent-faults": {"title": "Two independent faults", "summary": "Database pressure and catalog CPU saturation overlap. They should form separate incidents."},
}
DEPENDENCIES = {"edge-gateway": ["checkout-api"], "checkout-api": ["orders-db"], "orders-db": [], "catalog-api": []}
TRAINING_POINTS = 50
TOTAL_POINTS = 100
Z_THRESHOLD = 6.0


@dataclass(frozen=True)
class Observation:
    service: str
    metric: str
    minute: int
    value: float


def generate(scenario: str, seed: int = 42) -> list[Observation]:
    """Generate a deterministic incident exercise, never production telemetry."""
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario")
    rng = random.Random(seed)
    rows = []
    for minute in range(TOTAL_POINTS):
        for service in SERVICES:
            for metric, (centre, noise, _unit, _limit) in METRICS.items():
                value = centre + rng.gauss(0, noise)
                if minute >= 60 and scenario in {"database-pressure", "independent-faults"}:
                    if service == "orders-db" and metric == "pool_pct":
                        value += 65
                    if service == "orders-db" and metric == "latency_ms":
                        value += 370
                    if service == "checkout-api" and metric == "latency_ms" and minute >= 62:
                        value += 300
                    if service in {"checkout-api", "edge-gateway"} and metric == "error_pct" and minute >= 64:
                        value += 6
                if scenario == "memory-growth" and minute >= 60 and service == "checkout-api":
                    if metric == "memory_pct":
                        value += (minute - 59) * 1.3
                    if metric == "latency_ms":
                        value += (minute - 59) * 9
                if scenario == "independent-faults" and minute >= 70 and service == "catalog-api":
                    if metric == "cpu_pct":
                        value += 60
                    if metric == "latency_ms":
                        value += 280
                upper = 100 if metric.endswith("pct") else math.inf
                rows.append(Observation(service, metric, minute, round(min(upper, max(0, value)), 3)))
    return rows


def detect(rows: list[Observation], training_points: int = TRAINING_POINTS, operational_limits: dict | None = None) -> list[dict]:
    """Collapse consecutive anomalous observations into one metric finding.

    Require three consecutive breaches to reduce single-spike noise. A robust
    median/MAD score and a fixed domain limit can independently trigger it.
    This is a statistical detector, not a trained deep-learning model.
    """
    operational_limits = {key: value[3] for key, value in METRICS.items()} if operational_limits is None else operational_limits
    streams = defaultdict(list)
    for row in rows:
        streams[(row.service, row.metric)].append(row)
    findings = []
    for (service, metric), stream in sorted(streams.items()):
        stream.sort(key=lambda point: point.minute)
        baseline = [row.value for row in stream if row.minute < training_points]
        if len(baseline) < 20:
            continue
        median = statistics.median(baseline)
        mad = statistics.median(abs(value - median) for value in baseline)
        scale = max(1.4826 * mad, METRICS[metric][1] * 0.5)
        active = []
        groups = []
        for row in stream:
            z_score = (row.value - median) / scale
            breached = row.minute >= training_points and (z_score > Z_THRESHOLD or row.value > operational_limits.get(metric, math.inf))
            if breached:
                if active and row.minute != active[-1].minute + 1:
                    groups.append(active)
                    active = []
                active.append(row)
            elif active:
                groups.append(active)
                active = []
        if active:
            groups.append(active)
        for group in groups:
            if len(group) < 3:
                continue
            peak = max(group, key=lambda point: point.value)
            findings.append({
                "id": f"{service}:{metric}:{group[0].minute}",
                "service": service, "metric": metric, "unit": METRICS[metric][2],
                "start_minute": group[0].minute, "end_minute": group[-1].minute,
                "peak": peak.value, "baseline": round(median, 3),
                "robust_z": round((peak.value - median) / scale, 2),
                "observations": len(group),
                "reason": "Sustained deviation from the opening baseline or a fixed operational limit",
            })
    return sorted(findings, key=lambda item: (item["start_minute"], item["id"]))


def related(left: str, right: str, dependencies: dict | None = None) -> bool:
    """Dependency reachability; independent branches must not merge by time alone."""
    dependencies = DEPENDENCIES if dependencies is None else dependencies
    def reachable(start, target):
        pending, seen = [start], set()
        while pending:
            item = pending.pop()
            if item == target:
                return True
            if item not in seen:
                seen.add(item)
                pending.extend(dependencies.get(item, []))
        return False
    return reachable(left, right) or reachable(right, left)


def correlate(findings: list[dict], dependencies: dict | None = None) -> list[dict]:
    """Connected components over overlapping windows and dependency reachability."""
    groups = []
    remaining = list(findings)
    while remaining:
        component, pending = [], [remaining.pop(0)]
        while pending:
            item = pending.pop()
            component.append(item)
            connected = [other for other in remaining if related(item["service"], other["service"], dependencies) and
                         item["start_minute"] <= other["end_minute"] + 5 and other["start_minute"] <= item["end_minute"] + 5]
            for other in connected:
                remaining.remove(other)
                pending.append(other)
        groups.append(summarize(component))
    return sorted(groups, key=lambda item: item["start_minute"])


def summarize(evidence: list[dict]) -> dict:
    keys = {(item["service"], item["metric"]) for item in evidence}
    hypotheses = []
    if ("orders-db", "pool_pct") in keys:
        hypotheses.append({"title": "Database connection pressure may be propagating upstream", "basis": [item["id"] for item in evidence if item["metric"] in {"pool_pct", "latency_ms", "error_pct"}], "strength": "supported pattern", "next_check": "Inspect active connections, long-running queries and application pool settings. Check deployment changes before assigning a cause."})
    for service in sorted({item["service"] for item in evidence}):
        if (service, "memory_pct") in keys:
            hypotheses.append({"title": f"{service} memory pressure warrants investigation", "basis": [item["id"] for item in evidence if item["service"] == service], "strength": "plausible", "next_check": "Compare heap/GC behavior and request volume. Growth alone does not prove a memory leak."})
        if (service, "cpu_pct") in keys:
            hypotheses.append({"title": f"{service} CPU pressure may be limiting throughput", "basis": [item["id"] for item in evidence if item["service"] == service], "strength": "plausible", "next_check": "Compare workload and CPU profiles. Rule out an expected traffic spike."})
    if not hypotheses:
        hypotheses.append({"title": "Sustained service degradation; cause remains unknown", "basis": [item["id"] for item in evidence], "strength": "insufficient evidence", "next_check": "Collect deployment, trace and request-volume evidence before choosing a remediation."})
    services = sorted({item["service"] for item in evidence})
    critical = any(item["metric"] == "error_pct" and item["peak"] > 5 for item in evidence)
    return {"title": hypotheses[0]["title"], "severity": "critical" if critical else "warning", "services": services,
            "start_minute": min(item["start_minute"] for item in evidence), "end_minute": max(item["end_minute"] for item in evidence),
            "evidence": evidence, "hypotheses": hypotheses,
            "limitation": "Temporal correlation and dependencies support investigation, not causal proof. No automatic remediation."}


def analyze(scenario: str, seed: int = 42) -> dict:
    rows = generate(scenario, seed)
    findings = detect(rows)
    incidents = correlate(findings)
    origin = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    chart = []
    for service in SERVICES:
        points = [{"minute": row.minute, "value": row.value} for row in rows if row.service == service and row.metric == "latency_ms"]
        chart.append({"service": service, "points": points})
    return {"scenario": scenario, "scenario_title": SCENARIOS[scenario]["title"], "seed": seed,
            "mode": "synthetic exercise · statistical detector · heuristic hypotheses",
            "metrics_observed": len(rows), "baseline_minutes": TRAINING_POINTS,
            "start_time": origin.isoformat(), "end_time": (origin + timedelta(minutes=99)).isoformat(),
            "findings": findings, "incidents": incidents, "chart": chart,
            "dependencies": DEPENDENCIES, "detector": {"name": "median/MAD + operational limits", "robust_z_threshold": Z_THRESHOLD, "sustained_points": 3}}
