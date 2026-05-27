from __future__ import annotations

import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from src.config.settings import Settings
from src.evaluation.scoreboard import (
    LatencyMs,
    ModelSet,
    RetrieverMetrics,
    ScoreboardRow,
    add_row,
)


def test_scoreboard_endpoint_returns_empty_state_for_missing_artifact(tmp_path: Path) -> None:
    scoreboard_path = tmp_path / "missing-scoreboard.json"
    client = _client(tmp_path, scoreboard_path)

    response = client.get("/scoreboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["rows"] == []
    datetime.datetime.fromisoformat(payload["generated_at"])


def test_scoreboard_endpoint_returns_populated_artifact(tmp_path: Path) -> None:
    scoreboard_path = tmp_path / "scoreboard.json"
    row = ScoreboardRow(
        phase="P0",
        pipeline="baseline_hybrid",
        benchmark="nq",
        split="dev",
        retriever_metrics=RetrieverMetrics(
            recall_at_1=0.12,
            recall_at_5=0.34,
            recall_at_10=0.45,
            mrr_at_10=0.23,
            ndcg_at_10=0.31,
        ),
        latency_ms=LatencyMs(p50=120, p95=450),
        models=ModelSet(
            embedder="Qwen/Qwen3-Embedding-4B",
            reranker="cross-encoder/ms-marco-MiniLM-L-6-v2",
        ),
        commit_sha="abc1234",
        notes="baseline hybrid retrieval row",
    )
    add_row(row, path=scoreboard_path)
    client = _client(tmp_path, scoreboard_path)

    response = client.get("/scoreboard")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rows"]) == 1
    returned_row = payload["rows"][0]
    assert returned_row["phase"] == "P0"
    assert returned_row["pipeline"] == "baseline_hybrid"
    assert returned_row["commit_sha"] == "abc1234"


def _client(tmp_path: Path, scoreboard_path: Path) -> TestClient:
    app = create_app(
        settings=Settings(output_dir=tmp_path / "artifacts"),
        scoreboard_path_factory=lambda: scoreboard_path,
    )
    return TestClient(app)
