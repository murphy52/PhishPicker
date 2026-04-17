"""Tests for /about and /internal/reload behavior when a model artifact
exists in the data dir. Builds the artifact on-the-fly from seeded data.
"""

import json

import pytest
from fastapi.testclient import TestClient

from phishpicker.model.lightgbm_scorer import save_model_artifact


@pytest.fixture
def seeded_client_with_model(seeded_client, tmp_path):
    """seeded_client already seeded the DB. Train a tiny model against that
    DB and drop it in PHISHPICKER_DATA_DIR, then hit /internal/reload so the
    API picks it up without restart."""
    data_dir = seeded_client.app.state.settings.data_dir
    from phishpicker.db.connection import open_db
    from phishpicker.train.trainer import train_ranker

    conn = open_db(data_dir / "phishpicker.db", read_only=True)
    try:
        booster, cols, n = train_ranker(
            conn,
            cutoff_date="2099-01-01",
            negatives_per_positive=1,
            seed=0,
            num_iterations=5,
        )
    finally:
        conn.close()
    if n == 0:
        pytest.skip("seeded DB has no training groups")
    save_model_artifact(data_dir / "model.lgb", booster, cols)
    (data_dir / "metrics.json").write_text(
        json.dumps(
            {
                "trained_at": "2026-04-17T00:00:00Z",
                "mrr": 0.15,
                "top1": 0.08,
                "top5": 0.25,
                "top20": 0.55,
                "n_slots": 12,
                "baselines": {},
                "by_slot": {},
                "model_version": "0.2.0-test",
                "feature_columns": list(cols),
            }
        )
    )
    # Reload so the running TestClient sees the new artifact.
    r = seeded_client.post("/internal/reload", headers={"X-Admin-Token": "test-admin-token"})
    assert r.status_code == 200
    return seeded_client


def test_meta_reports_heuristic_when_no_model(seeded_client: TestClient):
    body = seeded_client.get("/meta").json()
    assert body["scorer"] == "heuristic"


def test_about_503_when_metrics_missing(seeded_client: TestClient):
    r = seeded_client.get("/about")
    assert r.status_code == 503


def test_meta_reports_lightgbm_when_model_present(seeded_client_with_model):
    body = seeded_client_with_model.get("/meta").json()
    assert body["scorer"] == "lightgbm"


def test_about_returns_metrics_when_present(seeded_client_with_model):
    r = seeded_client_with_model.get("/about")
    assert r.status_code == 200
    body = r.json()
    assert body["mrr"] == 0.15
    assert body["model_version"] == "0.2.0-test"


def test_internal_reload_requires_admin_token(seeded_client: TestClient):
    r = seeded_client.post("/internal/reload")
    assert r.status_code == 401


def test_internal_reload_accepts_correct_token(seeded_client: TestClient):
    r = seeded_client.post("/internal/reload", headers={"X-Admin-Token": "test-admin-token"})
    assert r.status_code == 200
    assert r.json()["reloaded"] is True
    assert r.json()["scorer"] == "heuristic"
