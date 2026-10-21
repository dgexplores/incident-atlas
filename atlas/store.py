"""SQLite repository with session isolation, bounded retention and review events."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, session TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS run_session ON runs(session, created);
            CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, session TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE, created TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return closing_connection(db)

    def create_run(self, session: str, payload: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        run_id = uuid.uuid4().hex
        result = {**payload, "id": run_id, "created": now}
        with self.connect() as db:
            for incident in result["incidents"]:
                incident["id"] = uuid.uuid4().hex
                incident["state"] = "open"
            db.execute("INSERT INTO runs VALUES(?,?,?,?)", (run_id, session, now, json.dumps(result)))
            for incident in result["incidents"]:
                db.execute("INSERT INTO incidents VALUES(?,?,?,?,?)", (incident["id"], run_id, session, "open", json.dumps(incident)))
                db.execute("INSERT INTO events(incident_id,created,kind,message) VALUES(?,?,?,?)", (incident["id"], now, "detected", "Statistical findings grouped into an incident."))
            # Public exercise storage is bounded; production needs explicit
            # tenant/auth policies and archival, not this demonstration policy.
            db.execute("DELETE FROM runs WHERE id IN (SELECT id FROM runs WHERE session=? ORDER BY created DESC LIMIT -1 OFFSET 12)", (session,))
            db.execute("DELETE FROM runs WHERE id IN (SELECT id FROM runs ORDER BY created DESC LIMIT -1 OFFSET 300)")
        return result

    def latest(self, session: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE session=? ORDER BY created DESC LIMIT 1", (session,)).fetchone()
            if not row:
                return None
            payload = json.loads(row["payload"])
            states = {item["id"]: item["state"] for item in db.execute("SELECT id,state FROM incidents WHERE run_id=?", (payload["id"],))}
            for incident in payload["incidents"]:
                incident["state"] = states[incident["id"]]
            return payload

    def incident(self, session: str, incident_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT state,payload FROM incidents WHERE id=? AND session=?", (incident_id, session)).fetchone()
            if not row:
                return None
            payload = json.loads(row["payload"])
            payload["state"] = row["state"]
            payload["events"] = [dict(item) for item in db.execute("SELECT created,kind,message FROM events WHERE incident_id=? ORDER BY id", (incident_id,))]
            return payload

    def review(self, session: str, incident_id: str, state: str, note: str) -> dict | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            row = db.execute("SELECT state FROM incidents WHERE id=? AND session=?", (incident_id, session)).fetchone()
            if not row:
                return None
            if state not in {"open", "investigating", "resolved"}:
                raise ValueError("invalid state")
            db.execute("UPDATE incidents SET state=? WHERE id=? AND session=?", (state, incident_id, session))
            db.execute("INSERT INTO events(incident_id,created,kind,message) VALUES(?,?,?,?)", (incident_id, now, "review", f"State: {state}. {note.strip()}"))
        return self.incident(session, incident_id)


class closing_connection:
    """Commit/rollback AND close; sqlite3's own context manager doesn't close."""
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type:
                self.db.rollback()
            else:
                self.db.commit()
        finally:
            self.db.close()
