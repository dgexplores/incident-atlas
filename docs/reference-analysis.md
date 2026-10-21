# Reference investigation: Signal0ne → Incident Atlas

Inspection date: 2026-10-22. Workflow: source-repository inspection under the
`reverse-engineer-anything` skill. The skill explicitly routes complete source
repositories to normal code tools; no binary decompiler or REA MCP was needed.

## Reference identities

- [Original archived repository](https://github.com/SzymonSt/docker-signalone),
  inspected commit `cc344076b79d507f6b3e3970a006dd4b89cfd3d2`.
- [Successor extension repository](https://github.com/Signal0ne/signal0ne-docker-extension),
  inspected commit `8866d61dd5fa3926eee56753f8730dd89b2a43f7`.
- [Original hackathon submission](https://devpost.com/software/signal0ne).

These repositories were read only. No upstream code or images were copied into
Atlas. Neither upstream application was executed; static source inspection does
not establish live behavior, availability or benchmark performance.

## Finding ledger

| Evidence | Observation | Design response | Boundary |
|---|---|---|---|
| Original `backend/main.go`, `backend/pkg/routers/main.router.go` | The archived backend exposes a Go/Gin HTTP API | Keep transport separate from incident logic in a new FastAPI service | This is the inspected snapshot, not necessarily the original hackathon revision |
| Successor `ext/agent/jobs/error_discovery.go` | Go collector scans container logs, maintains per-container time checkpoints and sends issue analysis requests | Separate detection, grouping and investigation outputs | Static inspection did not verify Docker runtime scheduling |
| Successor `ext/agent/helpers/helpers.go` | Collector tails up to 50 logs, parses timestamps, sends authenticated requests to `/api/agent/issues/analysis` | Use bounded exercises and explicit observation windows; no implicit Docker-socket access | Collector behavior was not executed |
| Original `backend/pkg/controllers/main.controller.go`, `LogAnalysisTask` | Issue processing looks up existing unresolved container issues and stores analysis using Mongo collections | Use parameterized SQLite records and a separate review event history | Only the issue-analysis portion of the large controller was followed |
| Original `solutionAgent/server.py` | Python FastAPI `/run_analysis` constructs primary and backup agents | Keep all hosted demo behavior deterministic without needing external credentials | Provider success, retry correctness and latency remain unverified |
| Original `solutionAgent/agent.py` | LangChain/HuggingFace agent summarizes logs, invokes a web-search tool, synthesizes possible solutions and extracts URLs | Evidence must point to exact local findings; label suggestions as hypotheses | Prompt wording is not a guarantee of grounded output |
| Successor `ext/frontend/src/app/app.component.*`, frontend inventory | Angular frontend and Docker extension assets are present | Build a visually independent evidence desk in local HTML/CSS/JS | Did not execute the original UI or claim feature parity |
| Bounded repository file search for anomaly/IsolationForest/model code | No standalone anomaly model implementation was located in these checked snapshots | Implement and test our own median/MAD detector | A bounded negative search does not establish that no model existed elsewhere |

## Independent implementation choices

Atlas uses source inspiration at the workflow level. Its detector, dependency
component grouping, fault generator, SQLite repository, session isolation and
frontend are new code. It introduces explicit evidence IDs and limitations,
while removing external model/search requirements from the public exercise.

The reconstruction is intentionally not a clone: Docker Desktop integration,
real container collection, user accounts, a vector database and external LLM
analysis remain outside this implementation. Those omissions are visible in
the README and user interface rather than hidden behind simulated output.

## Verification status

- Static source observations: inspected at the identities above.
- Atlas algorithm/API behavior: executable tests and generated evaluation.
- Original reference runtime: not executed.
- Atlas hosted deployment: parent workflow must verify after publication.
