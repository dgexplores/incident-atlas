# Incident Atlas

Investigate container resource changes with measured telemetry, statistical detection, runbook context and optional model-assisted hypotheses.

An original, AI-assisted Python application inspired by the operational problem addressed by [Signal0ne](https://devpost.com/software/signal0ne). No upstream source or awards are claimed. Independent v2 rebuild. The hosted default is offline; optional provider calls require configuration and operator authorization.

## Why this exists

A one-point CPU threshold can miss a meaningful change below its limit and alert on a harmless isolated spike. Incident Atlas freezes an opening baseline, requires consecutive deviations, groups related findings only when a dependency path is supplied, and keeps the investigation separate from remediation.

## Working capabilities

- Local `docker stats` collector for one to eight named running containers: CPU and memory only, bounded subprocess timeout, no shell execution, no socket mounted into the web application.
- Browser upload of a measured JSON capture, with stream completeness, duplicate, finite-value, service-count, body-size and dependency validation.
- Median/MAD detector with three consecutive breaches. For measured CPU, no universal 85% cap is applied: Docker percentages can exceed 100 on multiple cores.
- Dependency-aware incident grouping, exact finding IDs, local runbook matching and session-isolated SQLite review history.
- Optional OpenAI-compatible model call with operator-token authentication, bounded request/response settings and validation that returned evidence/runbook IDs exist. No autonomous commands or remediation.
- Four labelled synthetic exercises remain available without Docker or a provider.

## Run locally

Python 3.12+ and uv:

```sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m uvicorn atlas.app:app --host 127.0.0.1 --port 8051
```

Open http://127.0.0.1:8051. `/docs` displays the application API reference; `/openapi.json` is its schema. No account, Docker access or provider is required for the synthetic exercises.

## Collect actual container measurements

With Docker already running and a representative healthy workload:

```sh
.venv/bin/python -m atlas.collector my-container --samples 70 --baseline 50 --interval 5 --output telemetry.json
```

Upload `telemetry.json` in the interface. The first 50 samples establish the frozen baseline; only later points are candidates for detection. Sample indices are not minutes. The collector reports its measured average cadence because Docker stats may take longer than the requested interval. Capture a healthy baseline before introducing a fault. Stopped/missing selected containers cause collection to fail rather than silently produce an incomplete capture.

The web application accepts user-supplied measurements; it cannot authenticate that an uploaded file was actually collected by Docker. Non-CPU fixed resource limits retain their documented detector semantics. No latency or error-rate measurements are invented from CPU/memory stats.

## Optional model assistance

Configure these in the process environment; do not commit secrets:

```text
ATLAS_LLM_BASE_URL=https://your-provider.example/v1
ATLAS_LLM_MODEL=your-model
ATLAS_LLM_API_KEY=your-secret
ATLAS_OPERATOR_TOKEN=a-long-random-operator-token
```

A compatible local model server may use HTTP on localhost. Provider compatibility and quality require separate evaluation. Select an incident, review the runbooks, enter the operator token and explicitly request a hypothesis. This sends metric finding summaries and local runbooks to the configured provider; it does not send Docker logs. The token is cleared after submission and is not stored in browser storage.

Returned citation existence is validated, but citation correctness, reasoning quality and causal diagnosis are not proved. Raw log ingestion/RAG and trace ingestion are not implemented. Keep the service bound locally unless proper deployment authentication, quotas and TLS are added.

## Verification and measurable comparison

```sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/evaluate_telemetry.py
```

The generated evaluation covers 40 seeds across healthy data, isolated spikes, moderate sustained shifts and large shifts: 160 cases. The sustained robust detector reports TP80/FP0/TN80/FN0; a one-point 85% CPU threshold reports TP40/FP40/TN40/FN40. Mean alert eligibility occurs two samples after fault onset because three breaches are required. Full record: [telemetry evaluation](docs/telemetry-evaluation.json).

This demonstrates an advantage against that simple baseline on those constructed fixtures only. It is not a production false-alarm rate, live-container validation or comparison with Signal0ne. Docker daemon access timed out on the build host, so collector subprocess behavior is tested with recorded-shaped responses; an actual Docker capture remains unverified. Model calls are boundary-tested with a mocked HTTP provider, not scored for real-model quality.

## Architecture and interview discussion

```text
Local Docker CLI → bounded JSON capture → validated import → frozen-baseline detector
                                                        → dependency grouping
                                                        → evidence + runbooks
                                                        → optional model hypothesis
                                                        → human review / SQLite
```

Be prepared to explain median versus mean, MAD scale floors, why baseline leakage matters, CPU core semantics, time-window grouping, session isolation, provider output validation and why correlation is not causality. Changes are real code rather than a rename of an upstream project; AI assistance does not establish personal understanding, which should be demonstrated by modifying and debugging the system.

See [source study](docs/reference-analysis.md) for the original reference investigation. Existing [upstream-study notes](docs/upstream-study.md) describe the original, not this implementation.

## Demo and interview walkthrough

[Open the demo](https://dg-incident-atlas.onrender.com) · [Five-minute walkthrough](docs/DEMO.md). Free hosting can sleep; instance-local demo records may reset. External-provider and Jira modes are disabled unless configured and authorized.
