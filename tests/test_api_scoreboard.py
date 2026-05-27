from __future__ import annotations

import datetime
from pathlib import Path

import pytest
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

    response = client.get("/api/scoreboard")

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

    response = client.get("/api/scoreboard")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rows"]) == 1
    returned_row = payload["rows"][0]
    assert returned_row["phase"] == "P0"
    assert returned_row["pipeline"] == "baseline_hybrid"
    assert returned_row["commit_sha"] == "abc1234"


def test_spa_route_serves_index_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_path = _write_fake_dist(tmp_path)
    monkeypatch.setenv("RAG_WEB_DIST_PATH", str(dist_path))
    client = _client(tmp_path, tmp_path / "missing-scoreboard.json")

    response = client.get("/scoreboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == "<html><body>fake scoreboard shell</body></html>"


def test_spa_serves_index_for_root_when_dist_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_path = _write_fake_dist(tmp_path)
    monkeypatch.setenv("RAG_WEB_DIST_PATH", str(dist_path))
    client = _client(tmp_path, tmp_path / "missing-scoreboard.json")

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == "<html><body>fake scoreboard shell</body></html>"


def test_assets_mount_serves_built_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_path = _write_fake_dist(tmp_path)
    monkeypatch.setenv("RAG_WEB_DIST_PATH", str(dist_path))
    client = _client(tmp_path, tmp_path / "missing-scoreboard.json")

    response = client.get("/assets/foo.js")

    assert response.status_code == 200
    assert response.text == "console.log('fake asset');\n"


def test_spa_returns_404_for_missing_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_path = _write_fake_dist(tmp_path)
    monkeypatch.setenv("RAG_WEB_DIST_PATH", str(dist_path))
    client = _client(tmp_path, tmp_path / "missing-scoreboard.json")

    mounted_assets_response = client.get("/assets/does-not-exist.js")

    dist_without_assets_path = _write_fake_dist_without_assets(tmp_path)
    monkeypatch.setenv("RAG_WEB_DIST_PATH", str(dist_without_assets_path))
    client_without_assets = _client(tmp_path, tmp_path / "missing-scoreboard.json")

    unmounted_assets_response = client_without_assets.get("/assets/anything.js")

    assert mounted_assets_response.status_code == 404
    assert unmounted_assets_response.status_code == 404


def test_api_routes_win_and_unknown_api_paths_do_not_serve_spa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_path = _write_fake_dist(tmp_path)
    monkeypatch.setenv("RAG_WEB_DIST_PATH", str(dist_path))
    client = _client(tmp_path, tmp_path / "missing-scoreboard.json")

    scoreboard_response = client.get("/api/scoreboard")
    missing_api_response = client.get("/api/does-not-exist")

    assert scoreboard_response.status_code == 200
    assert scoreboard_response.json()["rows"] == []
    assert missing_api_response.status_code == 404


def _client(tmp_path: Path, scoreboard_path: Path) -> TestClient:
    app = create_app(
        settings=Settings(output_dir=tmp_path / "artifacts"),
        scoreboard_path_factory=lambda: scoreboard_path,
    )
    return TestClient(app)


def _write_fake_dist(tmp_path: Path) -> Path:
    dist_path = tmp_path / "web-dist"
    assets_path = dist_path / "assets"
    assets_path.mkdir(parents=True)
    (dist_path / "index.html").write_text(
        "<html><body>fake scoreboard shell</body></html>",
        encoding="utf-8",
    )
    (assets_path / "foo.js").write_text(
        "console.log('fake asset');\n",
        encoding="utf-8",
    )
    (dist_path / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    return dist_path


def _write_fake_dist_without_assets(tmp_path: Path) -> Path:
    dist_path = tmp_path / "web-dist-no-assets"
    dist_path.mkdir(parents=True)
    (dist_path / "index.html").write_text(
        "<html><body>fake scoreboard shell</body></html>",
        encoding="utf-8",
    )
    return dist_path
