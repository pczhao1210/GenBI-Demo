import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from utils.config_manager import PROJECT_ROOT


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self, path=None):
        self.path = Path(path or PROJECT_ROOT / "data" / "runs.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, submission TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL, private TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL, seq INTEGER NOT NULL, event TEXT NOT NULL,
                    PRIMARY KEY (run_id, seq)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    run_id TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (run_id, id)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, state, private, submission):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT state, private FROM runs WHERE submission=?", (submission,)).fetchone()
            if old:
                if json.loads(old[1])["submission_input"] != private["submission_input"]:
                    raise ValueError("Submission ID already used for different input")
                return json.loads(old[0]), False
            db.execute("INSERT INTO runs VALUES (?, ?, ?, ?)",
                       (state["run_id"], submission, json.dumps(state), json.dumps(private)))
        return state, True

    def get(self, run_id, private=False):
        with self.connect() as db:
            row = db.execute("SELECT state, private FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[1 if private else 0])

    def update(self, run_id, change, event_type=None, payload=None, artifact=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            state = json.loads(row[0])
            change(state)
            if artifact is not None:
                db.execute("INSERT INTO artifacts VALUES (?, ?, ?)",
                           (run_id, artifact[0], json.dumps(artifact[1], ensure_ascii=False)))
            state["updated_at"] = utcnow()
            if event_type:
                seq = state.get("event_seq", 0) + 1
                state["event_seq"] = seq
                event = {"event_id": uuid4().hex, "seq": seq, "run_id": run_id,
                         "plan_version": state["plan_version"], "time": utcnow(),
                         "type": event_type, "payload": payload or {}}
                for key in ("step_id", "attempt_id"):
                    if key in (payload or {}):
                        event[key] = payload[key]
                db.execute("INSERT INTO events VALUES (?, ?, ?)", (run_id, seq, json.dumps(event)))
            db.execute("UPDATE runs SET state=? WHERE id=?", (json.dumps(state), run_id))
        return state

    def events(self, run_id, after=0):
        self.get(run_id)
        with self.connect() as db:
            rows = db.execute("SELECT event FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 500",
                              (run_id, after)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def put_artifact(self, run_id, payload):
        artifact_id = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO artifacts VALUES (?, ?, ?)",
                       (run_id, artifact_id, json.dumps(payload, ensure_ascii=False)))
        return artifact_id

    def artifact(self, run_id, artifact_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM artifacts WHERE run_id=? AND id=?",
                             (run_id, artifact_id)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return json.loads(row[0])

    def history(self, session_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT state FROM runs ORDER BY rowid DESC LIMIT 200").fetchall()
        return [state for row in rows if (state := json.loads(row[0]))
                and (session_id is None or state["session_id"] == session_id)]

    def replay(self, run_id):
        state = self.get(run_id)
        with self.connect() as db:
            artifacts = db.execute("SELECT id, payload FROM artifacts WHERE run_id=?", (run_id,)).fetchall()
            events = db.execute("SELECT event FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return {"kind": "HISTORICAL_REPLAY", "snapshot": state,
                "artifacts": {key: json.loads(value) for key, value in artifacts},
                "events": [json.loads(row[0]) for row in events]}
