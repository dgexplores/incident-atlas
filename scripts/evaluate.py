"""Reproduce synthetic scenario detection metrics; no ground-truth production claim."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas.domain import analyze  # noqa: E402 - runnable from a fresh source checkout


def evaluate():
    seeds = range(1000, 1020)
    healthy_false_positive_runs = 0
    correct_fault_runs = 0
    scenarios = {"database-pressure": 1, "memory-growth": 1, "independent-faults": 2}
    details = []
    for seed in seeds:
        healthy_false_positive_runs += bool(analyze("healthy", seed)["incidents"])
        for scenario, expected in scenarios.items():
            actual = len(analyze(scenario, seed)["incidents"])
            correct_fault_runs += actual == expected
            details.append({"seed": seed, "scenario": scenario, "expected_incidents": expected, "actual_incidents": actual})
    return {"dataset": "deterministically generated synthetic telemetry", "evaluation_seed_range": [1000, 1019],
            "showcase_seed": 42, "healthy_runs": 20, "false_positive_runs": healthy_false_positive_runs,
            "fault_runs": 60, "fault_runs_with_expected_incident_count": correct_fault_runs,
            "healthy_run_false_positive_rate": healthy_false_positive_runs / 20,
            "fault_run_incident_count_accuracy": correct_fault_runs / 60,
            "limitations": ["Known synthetic fault families; not unseen-fault generalization.", "Incident count agreement does not establish causal diagnosis correctness.", "No production data, LLM evaluation, MTTR improvement or deployment uptime measurement."],
            "details": details}


if __name__ == "__main__":
    report = evaluate()
    target = Path(__file__).resolve().parents[1] / "docs" / "evaluation.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, indent=2))
