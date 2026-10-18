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
                CREATE INDEX IF NOT EXISTS runs_session
                    ON runs(json_extract(state, '$.session_id'));
                CREATE INDEX IF NOT EXISTS runs_database
                    ON runs(json_extract(state, '$.database'));
                CREATE INDEX IF NOT EXISTS runs_session_status
                    ON runs(json_extract(state, '$.session_id'), json_extract(state, '$.status'));
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
        column = "private" if private else "state"
        with self.connect() as db:
            row = db.execute(f"SELECT {column} FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def status(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT json_extract(state, '$.status') FROM runs WHERE id=?",
                             (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row[0]

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
        with self.connect() as db:
            if db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone() is None:
                raise KeyError(run_id)
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
        query, params = "SELECT state FROM runs", ()
        if session_id is not None:
            query += " WHERE json_extract(state, '$.session_id') = ?"
            params = (session_id,)
        with self.connect() as db:
            rows = db.execute(query + " ORDER BY rowid DESC LIMIT 200", params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def history_page(self, session_id=None, before=None, limit=20, database=None, statuses=None, profile_id=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("History page limit must be from 1 to 100")
        if before is not None and (type(before) is not int or before < 1):
            raise ValueError("History cursor must be a positive integer")
        fields = ("run_id", "session_id", "question", "database", "status", "phase", "plan_version",
                  "event_seq", "created_at", "updated_at", "profile_id", "profile_name")
        columns = ", ".join(f"json_extract(state, '$.{field}')" for field in fields)
        filters, parameters = [], []
        for field, value in (("session_id", session_id), ("database", database)):
            if value is not None:
                filters.append(f"json_extract(state, '$.{field}') = ?")
                parameters.append(value)
        if profile_id is not None:
            filters.append("COALESCE(json_extract(state, '$.profile_id'), '') = ?")
            parameters.append(profile_id)
        if statuses is not None:
            if (not isinstance(statuses, list) or not statuses or any(status not in {
                    "QUEUED", "RUNNING", "WAITING_INPUT", "CANCELLING", "SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED"}
                    for status in statuses)):
                raise ValueError("Invalid run history status filter")
            filters.append("json_extract(state, '$.status') IN (" + ",".join("?" for _ in statuses) + ")")
            parameters.extend(statuses)
        if before is not None:
            filters.append("rowid < ?")
            parameters.append(before)
        query = f"SELECT rowid, {columns} FROM runs"
        if filters:
            query += " WHERE " + " AND ".join(filters)
        parameters.append(limit + 1)
        with self.connect() as db:
            rows = db.execute(query + " ORDER BY rowid DESC LIMIT ?", parameters).fetchall()
        selected = rows[:limit]
        return {"items": [dict(zip(fields, row[1:])) for row in selected],
                "next_cursor": selected[-1][0] if len(rows) > limit else None}

    def replay(self, run_id):
        state = self.get(run_id)
        with self.connect() as db:
            artifacts = db.execute("SELECT id, payload FROM artifacts WHERE run_id=?", (run_id,)).fetchall()
            events = db.execute("SELECT event FROM events WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
        return {"kind": "HISTORICAL_REPLAY", "snapshot": state,
                "artifacts": {key: json.loads(value) for key, value in artifacts},
                "events": [json.loads(row[0]) for row in events]}
