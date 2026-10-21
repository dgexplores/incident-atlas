"""HTTP interface for bounded, session-isolated synthetic incident exercises."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from atlas.domain import SCENARIOS, analyze
from atlas.store import Store

ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(application):
    application.state.store = Store(os.getenv("ATLAS_DB_PATH", str(ROOT / "data" / "atlas.db")))
    yield


app = FastAPI(title="Incident Atlas", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None,
              description="Synthetic incident exercises: statistical anomalies, dependency correlation and evidence-linked hypotheses. No automatic remediation or live infrastructure connection.")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def session_boundary(request: Request, call_next):
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin writes are not accepted."}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 16_384:
            return JSONResponse({"detail": "Request is too large."}, status_code=413)
    session = request.cookies.get("atlas_session", "")
    valid_session = len(session) == 48 and all(char in "0123456789abcdef" for char in session)
    request.state.session = session if valid_session else secrets.token_hex(24)
    response = await call_next(request)
    if not valid_session:
        response.set_cookie("atlas_session", request.state.session, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=86400)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class Exercise(BaseModel):
    scenario: Literal["database-pressure", "memory-growth", "healthy", "independent-faults"]
    seed: int = Field(default=42, ge=0, le=1_000_000)


class Review(BaseModel):
    state: Literal["open", "investigating", "resolved"]
    note: str = Field(default="", max_length=1500)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/docs", include_in_schema=False)
def api_reference():
    return FileResponse(ROOT / "static" / "docs.html")


@app.get("/healthz")
def health():
    return {"status": "ok", "mode": "synthetic-exercises", "external_actions": False}


@app.get("/api/scenarios")
def scenarios():
    return [{"id": key, **value} for key, value in SCENARIOS.items()]


@app.get("/api/workspace")
def workspace(request: Request):
    store = app.state.store
    latest = store.latest(request.state.session)
    if latest is None:
        latest = store.create_run(request.state.session, analyze("database-pressure"))
    return latest


@app.post("/api/exercises", status_code=201)
def exercise(payload: Exercise, request: Request):
    return app.state.store.create_run(request.state.session, analyze(payload.scenario, payload.seed))


@app.get("/api/incidents/{incident_id}")
def incident(incident_id: str, request: Request):
    result = app.state.store.incident(request.state.session, incident_id)
    if result is None:
        raise HTTPException(404, "Incident not found in this browser's exercise.")
    return result


@app.post("/api/incidents/{incident_id}/review")
def review(incident_id: str, payload: Review, request: Request):
    result = app.state.store.review(request.state.session, incident_id, payload.state, payload.note)
    if result is None:
        raise HTTPException(404, "Incident not found in this browser's exercise.")
    return result
