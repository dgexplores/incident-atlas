"""Collect real Docker stats locally; never mount the Docker socket in the web app."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import time


NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


def parse_stats(output: str, sample: int) -> list[dict]:
    points = []
    for line in output.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        service = row.get("Name", "")
        if not NAME.fullmatch(service):
            raise ValueError("Docker returned an unsupported container name.")
        for field, metric in (("CPUPerc", "cpu_pct"), ("MemPerc", "memory_pct")):
            value = float(str(row[field]).removesuffix("%"))
            limit = 100 if metric == "memory_pct" else 100_000
            if not math.isfinite(value) or not 0 <= value <= limit:
                raise ValueError("Docker returned an invalid percentage.")
            points.append({"service": service, "metric": metric, "minute": sample, "value": value})
    return points


def collect(names: list[str], samples: int, interval: float, baseline: int = 50) -> dict:
    if not 1 <= len(names) <= 8 or any(not NAME.fullmatch(name) for name in names) or len(set(names)) != len(names):
        raise ValueError("Choose one to eight distinct Docker container names, not shell commands.")
    if not 20 <= baseline <= 120 or not baseline + 3 <= samples <= 500 or not 1 <= interval <= 3600:
        raise ValueError("Need 20–120 baseline samples, at least three later samples, and a 1–3600 second interval.")
    points = []
    started = time.monotonic()
    captured_at = datetime.now(timezone.utc).isoformat()
    durations = []
    for sample in range(samples):
        before = time.monotonic()
        result = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *names],
                                capture_output=True, text=True, timeout=20, check=True)
        rows = parse_stats(result.stdout, sample)
        if {p["service"] for p in rows} != set(names) or len(rows) != len(names) * 2:
            raise ValueError("A selected container is stopped, missing or returned duplicate stats; no incomplete batch saved.")
        points.extend(rows)
        durations.append(time.monotonic() - before)
        if sample < samples - 1:
            time.sleep(max(0, interval - (time.monotonic() - before)))
    # Docker stats itself may take longer than the requested interval. Report
    # the measured average cadence rather than mislabelling it as exact timing.
    observed_interval = (time.monotonic() - started - durations[-1]) / (samples - 1)
    return {"source": f"Docker stats captured {captured_at}", "sample_interval_seconds": max(1, observed_interval),
            "baseline_points": baseline, "points": points, "dependencies": {}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("containers", nargs="+")
    parser.add_argument("--samples", type=int, default=70)
    parser.add_argument("--baseline", type=int, default=50)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--output", type=Path, default=Path("telemetry.json"))
    args = parser.parse_args()
    try:
        result = collect(args.containers, args.samples, args.interval, args.baseline)
    except (ValueError, subprocess.SubprocessError, FileNotFoundError) as exc:
        parser.exit(1, f"Collection failed: {exc}\nCheck Docker is running and the selected containers are healthy.\n")
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Saved {len(result['points'])} measured observations to {args.output}. Upload this file in Incident Atlas.")


if __name__ == "__main__":
    main()
