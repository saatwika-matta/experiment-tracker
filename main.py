import json
import random
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

DB = "experiments.db"
MODEL_VERSION = "toy-model-0.1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    feed_blend TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    parameters TEXT NOT NULL,
    model_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    component TEXT NOT NULL,
    purity_wt_pct REAL NOT NULL CHECK (purity_wt_pct BETWEEN 0 AND 100)
);
CREATE INDEX IF NOT EXISTS idx_runs_experiment ON runs(experiment_id);
CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with closing(get_conn()) as conn, conn:
        conn.executescript(SCHEMA)


init_db()
app = FastAPI(title="Experiment Tracker")


# ---------- Schemas (validation lives here) ----------
class ExperimentIn(BaseModel):
    name: str = Field(min_length=1)
    feed_blend: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class RunParams(BaseModel):
    temperature_c: float = Field(ge=-100, le=200)
    pressure_bar: float = Field(gt=0, le=50)
    solvent_ratio: float = Field(gt=0, le=10)


# ---------- Toy "engineering model" ----------
def toy_model(p: dict) -> dict:
    """Stand-in for a real separation model. Returns purity per component."""
    base = 90 + 2 * p["solvent_ratio"] - 0.1 * abs(p["temperature_c"] - 25)
    return {
        "R-32": round(max(0.0, min(99.9, base + random.uniform(-0.5, 0.5))), 2),
        "R-125": round(max(0.0, min(99.9, base - 1 + random.uniform(-0.5, 0.5))), 2),
    }


def simulate_run(run_id: int, params: dict) -> None:
    with closing(get_conn()) as conn, conn:
        conn.execute("UPDATE runs SET status='running', started_at=? WHERE id=?", (now(), run_id))
    try:
        time.sleep(2)  # pretend this is a slow simulation
        purities = toy_model(params)
        with closing(get_conn()) as conn, conn:
            conn.executemany(
                "INSERT INTO results (run_id, component, purity_wt_pct) VALUES (?, ?, ?)",
                [(run_id, comp, val) for comp, val in purities.items()],
            )
            conn.execute("UPDATE runs SET status='done', finished_at=? WHERE id=?", (now(), run_id))
    except Exception as exc:
        with closing(get_conn()) as conn, conn:
            conn.execute(
                "UPDATE runs SET status='failed', error=?, finished_at=? WHERE id=?",
                (str(exc), now(), run_id),
            )


# ---------- Endpoints ----------
@app.post("/experiments", status_code=201)
def create_experiment(exp: ExperimentIn):
    with closing(get_conn()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO experiments (name, feed_blend, created_by, created_at) VALUES (?, ?, ?, ?)",
            (exp.name, exp.feed_blend, exp.created_by, now()),
        )
        return {"id": cur.lastrowid, **exp.model_dump()}


@app.post("/experiments/{experiment_id}/runs", status_code=202)
def start_run(experiment_id: int, params: RunParams, background_tasks: BackgroundTasks):
    with closing(get_conn()) as conn, conn:
        if conn.execute("SELECT 1 FROM experiments WHERE id=?", (experiment_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Experiment not found")
        cur = conn.execute(
            "INSERT INTO runs (experiment_id, parameters, model_version, status, created_at) "
            "VALUES (?, ?, ?, 'queued', ?)",
            (experiment_id, json.dumps(params.model_dump()), MODEL_VERSION, now()),
        )
        run_id = cur.lastrowid
    background_tasks.add_task(simulate_run, run_id, params.model_dump())
    return {"run_id": run_id, "status": "queued"}


@app.get("/runs/{run_id}")
def get_run(run_id: int):
    with closing(get_conn()) as conn:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        results = conn.execute(
            "SELECT component, purity_wt_pct FROM results WHERE run_id=?", (run_id,)
        ).fetchall()
    data = dict(run)
    data["parameters"] = json.loads(data["parameters"])
    data["results"] = [dict(r) for r in results]
    return data


@app.get("/experiments/{experiment_id}/summary")
def experiment_summary(experiment_id: int):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT res.component, MAX(res.purity_wt_pct) AS best_purity, res.run_id
            FROM results res
            JOIN runs r ON r.id = res.run_id
            WHERE r.experiment_id = ?
            GROUP BY res.component
            """,
            (experiment_id,),
        ).fetchall()
    return {"experiment_id": experiment_id, "best": [dict(r) for r in rows]}
