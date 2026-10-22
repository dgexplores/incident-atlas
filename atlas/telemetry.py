"""Validate measured telemetry and reuse the statistical incident pipeline."""
from collections import Counter
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from atlas.domain import METRICS, Observation, correlate, detect


class MetricPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    service: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    metric: Literal["cpu_pct", "memory_pct", "latency_ms", "error_pct", "pool_pct"]
    minute: int = Field(ge=0, le=599)
    value: float = Field(ge=0, le=100_000)

    @model_validator(mode="after")
    def percentage_range(self):
        if self.metric in {"memory_pct", "error_pct", "pool_pct"} and self.value > 100:
            raise ValueError("Memory, error and pool percentages cannot exceed 100.")
        return self


class TelemetryBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(default="uploaded telemetry", min_length=1, max_length=120)
    sample_interval_seconds: float = Field(default=5, ge=1, le=3600, allow_inf_nan=False)
    baseline_points: int = Field(default=50, ge=20, le=120)
    points: list[MetricPoint] = Field(min_length=23, max_length=8000)
    dependencies: dict[str, list[str]] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def validate_streams(self):
        services = {p.service for p in self.points}
        if len(services) > 16:
            raise ValueError("At most 16 services per batch.")
        keys = [(p.service, p.metric, p.minute) for p in self.points]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate service/metric/sample observations are not accepted.")
        counts = Counter((p.service, p.metric) for p in self.points if p.minute < self.baseline_points)
        streams = {(p.service, p.metric) for p in self.points}
        for stream in streams:
            if counts[stream] != self.baseline_points:
                raise ValueError("Every stream needs a complete opening baseline window.")
            after = [p for p in self.points if (p.service, p.metric) == stream and p.minute >= self.baseline_points]
            if len(after) < 3:
                raise ValueError("Every stream needs at least three observations after baseline.")
        for source, targets in self.dependencies.items():
            if source not in services or len(targets) > 16 or not set(targets) <= services:
                raise ValueError("Dependency edges must reference observed services, with at most 16 targets.")
        return self


def analyze_telemetry(batch: TelemetryBatch) -> dict:
    rows = [Observation(p.service, p.metric, p.minute, p.value) for p in batch.points]
    findings = detect(rows, training_points=batch.baseline_points,
                      operational_limits={key: value[3] for key, value in METRICS.items() if key != "cpu_pct"})
    services = sorted({p.service for p in batch.points})
    chart_metric = "cpu_pct" if any(p.metric == "cpu_pct" for p in batch.points) else batch.points[0].metric
    chart = [{"service": service, "points": [{"minute": p.minute, "value": p.value} for p in sorted(batch.points, key=lambda p: p.minute)
              if p.service == service and p.metric == chart_metric]} for service in services]
    return {"scenario": "measured-telemetry", "scenario_title": batch.source, "seed": None,
            "mode": "uploaded measurements · statistical detector · heuristic hypotheses",
            "source_kind": "user-supplied measurements", "sample_interval_seconds": batch.sample_interval_seconds,
            "baseline_duration_seconds": batch.baseline_points * batch.sample_interval_seconds, "baseline_points": batch.baseline_points,
            "chart_metric": chart_metric, "metrics_observed": len(rows), "chart": [c for c in chart if c["points"]],
            "findings": findings, "incidents": correlate(findings, dependencies=batch.dependencies),
            "dependencies": batch.dependencies, "start_time": datetime.now(timezone.utc).isoformat(),
            "detector": {"name": "median/MAD + operational limits", "robust_z_threshold": 6, "sustained_points": 3,
                         "cpu_absolute_limit": None, "note": "Measured CPU uses baseline deviation, not a one-core 85% limit."}}
