# Experiment Tracker API

A small FastAPI service for tracking engineering experiments and simulation runs, built to explore how to turn engineering models into reliable, traceable tools.

## What it does
- Create experiments (e.g., a feed blend being tested)
- Start simulation runs with validated parameters (temperature, pressure, solvent ratio)
- Runs execute in the background; the API responds immediately with status `queued`
- Every run records its **parameters, model version, status, and timestamps** (data lineage)
- Summarize the best purity per component for an experiment

## Design decisions
- **Lineage:** each run stores the exact inputs and model version that produced its results, so any result can be traced and reproduced.
- **Immutable runs:** reruns create new records; results are never overwritten.
- **Validation:** Pydantic rejects physically impossible inputs (e.g., negative pressure) with a 422 error.
- **Long-running jobs:** simulations run as background tasks so requests don't block. A production version would use a job queue (e.g., Celery or RQ).
- **Data integrity:** foreign keys, CHECK constraints, and indexes in the database schema.

> The "model" here is a toy function standing in for a real engineering simulation.

## Run locally
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```
Open http://127.0.0.1:8000/docs for interactive API docs.

## Tests
```bash
pytest -q
```
Tests cover lineage recording, input validation, and missing-experiment handling.

## Tech
Python, FastAPI, Pydantic, SQLite, pytest
