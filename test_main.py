import os

from fastapi.testclient import TestClient

if os.path.exists("experiments.db"):
    os.remove("experiments.db")

from main import app  # noqa: E402

client = TestClient(app)


def create_experiment():
    res = client.post(
        "/experiments",
        json={"name": "Test", "feed_blend": "R-410A", "created_by": "tester"},
    )
    assert res.status_code == 201
    return res.json()["id"]


def test_run_completes_with_lineage():
    exp_id = create_experiment()
    params = {"temperature_c": 25, "pressure_bar": 5, "solvent_ratio": 3}
    res = client.post(f"/experiments/{exp_id}/runs", json=params)
    assert res.status_code == 202
    run_id = res.json()["run_id"]

    # TestClient runs background tasks before returning, so the run is finished here
    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "done"
    assert run["parameters"] == params          # lineage: inputs recorded
    assert run["model_version"] == "toy-model-0.1"  # lineage: model version recorded
    assert all(0 <= r["purity_wt_pct"] <= 100 for r in run["results"])


def test_invalid_pressure_is_rejected():
    exp_id = create_experiment()
    res = client.post(
        f"/experiments/{exp_id}/runs",
        json={"temperature_c": 25, "pressure_bar": -1, "solvent_ratio": 3},
    )
    assert res.status_code == 422


def test_unknown_experiment_returns_404():
    res = client.post(
        "/experiments/9999/runs",
        json={"temperature_c": 25, "pressure_bar": 5, "solvent_ratio": 3},
    )
    assert res.status_code == 404
