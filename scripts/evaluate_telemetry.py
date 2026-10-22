"""Compare sustained robust detection with one fixed CPU threshold on generated fixtures."""
import json
from pathlib import Path
import random
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas.telemetry import TelemetryBatch, analyze_telemetry


def evaluate():
    counts = {name: {"tp": 0, "fp": 0, "tn": 0, "fn": 0} for name in ["sustained_robust", "fixed_85_threshold"]}
    delays = []
    for seed in range(40):
        for scenario in ["healthy", "single_spike", "moderate_shift", "large_shift"]:
            rng = random.Random(seed)
            values = [max(0, 30 + rng.gauss(0, 1.8)) for _ in range(60)]
            if scenario == "single_spike":
                values[35] = 98
            if scenario.endswith("shift"):
                values[30:] = [v + (35 if scenario == "moderate_shift" else 65) for v in values[30:]]
            rows = [{"service": "benchmark-worker", "metric": "cpu_pct", "minute": i, "value": value} for i, value in enumerate(values)]
            result = analyze_telemetry(TelemetryBatch.model_validate({"baseline_points": 20, "points": rows}))
            expected = scenario.endswith("shift")
            actual = {"sustained_robust": bool(result["findings"]), "fixed_85_threshold": any(v > 85 for v in values[20:])}
            for method, predicted in actual.items():
                counts[method]["tp" if predicted and expected else "fp" if predicted else "fn" if expected else "tn"] += 1
            if result["findings"] and expected:
                # A finding starts at its first breach, but is emitted only on the third.
                delays.append(result["findings"][0]["start_minute"] + 2 - 30)
    return {"cases": 160, "seeds": 40, "scenarios": ["healthy", "single_spike", "moderate_shift", "large_shift"],
            "opening_baseline_samples": 20, "counts": counts, "mean_detection_delay_samples": statistics.mean(delays),
            "limitations": "Generated CPU fixtures, not captured Docker data or independent validation. Moderate shifts are labelled anomalous by construction. Comparison is only against a one-point 85% threshold, not Signal0ne or any original winner."}


if __name__ == "__main__":
    result = evaluate()
    target = Path(__file__).resolve().parents[1] / "docs" / "telemetry-evaluation.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
