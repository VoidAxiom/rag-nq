from __future__ import annotations

import datetime
import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import main as api_main
from app.api.schemas import SuiteConfig
from src.config.settings import Settings
from src.evaluation import eval_suite
from src.evaluation.eval_suite import EvalSuite, SuiteEntry
from src.models.query_schemas import GroundedAnswer, PassageHit, RetrievalMetrics
from src.retrieval.qdrant_retrievers import Mode


class FakeRetriever:
    def __init__(self, *, mode: Mode, sleep_seconds: float = 0.0) -> None:
        self.mode = mode
        self.sleep_seconds = sleep_seconds
        self.last_retrieval_metrics = RetrievalMetrics()

    def retrieve_with_metrics(
        self, query: str, top_k: int
    ) -> tuple[list[PassageHit], RetrievalMetrics | None]:
        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)
        hits = [_hit(point_id) for point_id in _point_ids_for_query(query, self.mode)]
        return hits[:top_k], self.last_retrieval_metrics


class FakeGenerator:
    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer:
        del hits
        return GroundedAnswer(answer=f"Answer for {query}", abstained=False)


def test_adhoc_two_combos_end_to_end_event_sequence(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response, events = _post_stream(client, _adhoc_payload())

    assert response.status_code == 200
    assert [event for event, _payload in events][0] == "started"
    assert [event for event, _payload in events][-1] == "done"
    assert _count_events(events, "question_started") == 2
    assert _count_events(events, "result") == 2
    assert _count_events(events, "combo_aggregate") == 2
    assert _count_events(events, "error") == 0
    started = events[0][1]
    assert started["total_questions"] == 1
    assert started["combo_ids"] == ["dense", "sparse"]


def test_suite_question_set_emits_n_results_per_combo(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    suite = _write_suite(settings.output_dir / "eval_suites", entry_count=3)
    client = _client(tmp_path, settings=settings)
    payload = _sample_payload(
        question_set={"kind": "suite", "suite_id": suite.id},
        combos=_two_combos(),
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    result_events = [payload for event, payload in events if event == "result"]
    assert len(result_events) == len(suite.entries) * 2
    assert _result_count_by_combo(result_events) == {"dense": 3, "sparse": 3}


def test_sample_first_question_set_emits_size_results_per_combo(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    _write_eval_questions(settings.output_dir / "eval_questions", count=5)
    client = _client(tmp_path, settings=settings)
    payload = _sample_payload(
        question_set={"kind": "sample", "benchmark": "nq", "size": 2, "strategy": "first"},
        combos=_two_combos(),
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    result_events = [payload for event, payload in events if event == "result"]
    assert _result_count_by_combo(result_events) == {"dense": 2, "sparse": 2}


def test_under_two_combos_rejected_with_422(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = _sample_payload(question_set=_adhoc_question_set(), combos=[_combo("dense")])

    response = client.post("/api/benchmark/stream", json=payload)

    assert response.status_code == 422


def test_over_five_combos_rejected_with_422(tmp_path: Path) -> None:
    client = _client(tmp_path)
    combos = [_combo(f"combo-{i}") for i in range(6)]
    payload = _sample_payload(question_set=_adhoc_question_set(), combos=combos)

    response = client.post("/api/benchmark/stream", json=payload)

    assert response.status_code == 422


def test_duplicate_combo_ids_rejected_with_422(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = _sample_payload(
        question_set=_adhoc_question_set(),
        combos=[_combo("dup", mode="dense"), _combo("dup", mode="sparse")],
    )

    response = client.post("/api/benchmark/stream", json=payload)

    assert response.status_code == 422


def test_openai_combo_without_opt_in_envs_returns_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RAG_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAG_OPENAI_OPT_IN", raising=False)
    client = _client(tmp_path)
    payload = _sample_payload(
        question_set=_adhoc_question_set(),
        combos=[
            _combo("openai", mode="dense", generation_provider="openai"),
            _combo("control", mode="sparse", generation_provider=None),
        ],
    )

    response = client.post("/api/benchmark/stream", json=payload)

    assert response.status_code == 422
    assert "OpenAI" in response.json()["detail"]


def test_openai_combo_with_opt_in_envs_opens_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAG_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("RAG_OPENAI_OPT_IN", "1")
    client = _client(tmp_path)
    payload = _sample_payload(
        question_set=_adhoc_question_set(),
        combos=[
            _combo("openai", mode="dense", generation_provider="openai"),
            _combo("control", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    assert [event for event, _payload in events][0] == "started"
    assert [event for event, _payload in events][-1] == "done"
    assert _count_events(events, "error") == 0


def test_unknown_generation_provider_rejected_with_422(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = _sample_payload(
        question_set=_adhoc_question_set(),
        combos=[
            _combo("bad-provider", mode="dense", generation_provider="anthropic"),
            _combo("control", mode="sparse", generation_provider=None),
        ],
    )

    response = client.post("/api/benchmark/stream", json=payload)

    assert response.status_code == 422
    assert "Input should be 'heuristic', 'http_json' or 'openai'" in response.text


def test_unknown_suite_id_emits_error_event_stream_ok(tmp_path: Path) -> None:
    client = _client(tmp_path)
    payload = _sample_payload(
        question_set={"kind": "suite", "suite_id": "missing-suite"},
        combos=_two_combos(),
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    assert [event for event, _payload in events] == ["started", "error", "done"]
    assert events[0][1]["total_questions"] == 0
    assert "missing-suite" in events[1][1]["message"]


def test_concurrency_two_combos_parallelize(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    _write_eval_questions(settings.output_dir / "eval_questions", count=2)
    client = _client(tmp_path, settings=settings, sleep_seconds=0.2)
    payload = _sample_payload(
        question_set={"kind": "sample", "benchmark": "nq", "size": 2, "strategy": "first"},
        combos=[
            _combo("dense", mode="dense", generation_provider=None),
            _combo("sparse", mode="sparse", generation_provider=None),
        ],
    )

    started_at = time.perf_counter()
    response, events = _post_stream(client, payload)
    elapsed = time.perf_counter() - started_at

    assert response.status_code == 200
    assert _count_events(events, "result") == 4
    assert elapsed >= 0.35
    assert elapsed < 0.6


def test_combo_aggregates_match_manual_mean_of_result_events(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    _write_eval_questions(settings.output_dir / "eval_questions", count=3)
    client = _client(tmp_path, settings=settings)
    payload = _sample_payload(
        question_set={"kind": "sample", "benchmark": "nq", "size": 3, "strategy": "first"},
        combos=[
            _combo("dense", mode="dense", generation_provider=None),
            _combo("sparse", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    for combo_id in ("dense", "sparse"):
        result_payloads = [
            payload
            for event, payload in events
            if event == "result" and payload["combo_id"] == combo_id
        ]
        final_aggregate = [
            payload
            for event, payload in events
            if event == "combo_aggregate" and payload["combo_id"] == combo_id
        ][-1]
        assert final_aggregate["completed_count"] == 3
        for metric in (
            "recall_at_1",
            "recall_at_5",
            "recall_at_10",
            "mrr_at_10",
            "ndcg_at_10",
        ):
            values = [payload["metrics"][metric] for payload in result_payloads]
            manual_mean = sum(values) / len(values)
            assert final_aggregate["running_metrics"][f"{metric}_mean"] == pytest.approx(
                manual_mean
            )


def test_combo_error_event_carries_failing_question_index(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    _write_eval_questions(settings.output_dir / "eval_questions", count=2)
    calls_by_mode: dict[Mode, int] = {}

    class FailingRetriever(FakeRetriever):
        def retrieve_with_metrics(
            self, query: str, top_k: int
        ) -> tuple[list[PassageHit], RetrievalMetrics | None]:
            calls_by_mode[self.mode] = calls_by_mode.get(self.mode, 0) + 1
            if self.mode == "dense" and calls_by_mode[self.mode] == 2:
                raise RuntimeError("planned second question failure")
            return super().retrieve_with_metrics(query, top_k)

    def retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        del settings
        return FailingRetriever(mode=mode)

    client = _client(tmp_path, settings=settings, retriever_factory=retriever_factory)
    payload = _sample_payload(
        question_set={"kind": "sample", "benchmark": "nq", "size": 2, "strategy": "first"},
        combos=[
            _combo("failing", mode="dense", generation_provider=None),
            _combo("control", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    failing_events = [
        (event, payload)
        for event, payload in events
        if payload.get("combo_id") == "failing"
    ]
    error_payload = [payload for event, payload in failing_events if event == "error"][0]
    assert error_payload["combo_id"] == "failing"
    assert error_payload["question_index"] == 1
    assert "planned second question failure" in error_payload["message"]
    assert [event for event, _payload in failing_events].count("combo_aggregate") <= 1
    assert _result_count_by_combo(
        [payload for event, payload in events if event == "result"]
    ) == {"failing": 1, "control": 2}


def test_combo_error_at_first_question_emits_no_aggregate(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    _write_eval_questions(settings.output_dir / "eval_questions", count=1)

    class FailingRetriever(FakeRetriever):
        def retrieve_with_metrics(
            self, query: str, top_k: int
        ) -> tuple[list[PassageHit], RetrievalMetrics | None]:
            if self.mode == "dense":
                raise RuntimeError("planned first question failure")
            return super().retrieve_with_metrics(query, top_k)

    def retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        del settings
        return FailingRetriever(mode=mode)

    client = _client(tmp_path, settings=settings, retriever_factory=retriever_factory)
    payload = _sample_payload(
        question_set={"kind": "sample", "benchmark": "nq", "size": 1, "strategy": "first"},
        combos=[
            _combo("failing", mode="dense", generation_provider=None),
            _combo("control", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    failing_events = [
        (event, payload)
        for event, payload in events
        if payload.get("combo_id") == "failing"
    ]
    assert [event for event, _payload in failing_events] == ["question_started", "error"]
    error_payload = failing_events[-1][1]
    assert error_payload["question_index"] == 0
    assert "planned first question failure" in error_payload["message"]


def test_combo_error_emits_at_most_one_terminal_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    _write_eval_questions(settings.output_dir / "eval_questions", count=3)

    def retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        del settings
        return FakeRetriever(mode=mode)

    original_result_event_payload = api_main._result_event_payload

    def result_event_payload(result: api_main.ComboRunResult) -> dict:
        if result.combo_id == "failing" and result.question_index == 1:
            raise RuntimeError("planned payload failure")
        return original_result_event_payload(result)

    monkeypatch.setattr(api_main, "_result_event_payload", result_event_payload)

    client = _client(tmp_path, settings=settings, retriever_factory=retriever_factory)
    payload = _sample_payload(
        question_set={"kind": "sample", "benchmark": "nq", "size": 3, "strategy": "first"},
        combos=[
            _combo("failing", mode="dense", generation_provider=None),
            _combo("control", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    failing_events = [
        (event, payload)
        for event, payload in events
        if payload.get("combo_id") == "failing"
    ]
    error_payloads = [payload for event, payload in failing_events if event == "error"]
    assert len(error_payloads) == 1
    assert error_payloads[0]["combo_id"] == "failing"
    assert error_payloads[0]["question_index"] == 1
    assert "planned payload failure" in error_payloads[0]["message"]
    terminal_aggregates = [
        payload
        for event, payload in failing_events
        if event == "combo_aggregate" and payload["completed_count"] == 2
    ]
    assert len(terminal_aggregates) <= 1
    if terminal_aggregates:
        assert terminal_aggregates[0]["running_metrics"]["recall_at_1_mean"] is not None
    assert _result_count_by_combo(
        [payload for event, payload in events if event == "result"]
    ) == {"failing": 1, "control": 3}


def test_combo_error_event_emitted_even_if_aggregate_path_would_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    _write_eval_questions(settings.output_dir / "eval_questions", count=2)

    def retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        del settings
        return FakeRetriever(mode=mode)

    original_result_event_payload = api_main._result_event_payload

    def result_event_payload(result: api_main.ComboRunResult) -> dict:
        if result.combo_id == "failing" and result.question_index == 1:
            raise RuntimeError("planned payload failure")
        return original_result_event_payload(result)

    original_compute_running_aggregates = api_main.compute_running_aggregates

    def compute_running_aggregates(
        results: list[api_main.ComboRunResult],
    ) -> dict[str, float | None]:
        if results and results[0].combo_id == "failing" and len(results) == 2:
            raise RuntimeError("aggregate boom")
        return original_compute_running_aggregates(results)

    monkeypatch.setattr(api_main, "_result_event_payload", result_event_payload)
    monkeypatch.setattr(
        api_main, "compute_running_aggregates", compute_running_aggregates
    )

    client = _client(tmp_path, settings=settings, retriever_factory=retriever_factory)
    payload = _sample_payload(
        question_set={"kind": "sample", "benchmark": "nq", "size": 2, "strategy": "first"},
        combos=[
            _combo("failing", mode="dense", generation_provider=None),
            _combo("control", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    failing_events = [
        (event, payload)
        for event, payload in events
        if payload.get("combo_id") == "failing"
    ]
    error_payloads = [payload for event, payload in failing_events if event == "error"]
    assert len(error_payloads) == 1
    assert error_payloads[0]["combo_id"] == "failing"
    assert error_payloads[0]["question_index"] == 1
    assert "planned payload failure" in error_payloads[0]["message"]
    terminal_aggregates = [
        payload
        for event, payload in failing_events
        if event == "combo_aggregate" and payload["completed_count"] == 2
    ]
    assert terminal_aggregates == []


def test_combo_retrieve_k_override_routes_to_distinct_retrievers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, Mode]] = []

    def retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        calls.append((settings.retrieve_k, mode))
        return FakeRetriever(mode=mode)

    monkeypatch.setattr(api_main, "_default_retriever_factory", retriever_factory)
    app = api_main.create_app(settings=Settings(output_dir=tmp_path / "artifacts"))
    client = TestClient(app)
    payload = _sample_payload(
        question_set=_adhoc_question_set(),
        combos=[
            _combo(
                "retrieve-20",
                mode="dense",
                generation_provider=None,
                retrieve_k=20,
            ),
            _combo(
                "retrieve-50",
                mode="dense",
                generation_provider=None,
                retrieve_k=50,
            ),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    assert _count_events(events, "error") == 0
    assert (20, "dense") in calls
    assert (50, "dense") in calls


def test_rerank_model_name_off_disables_rerank(tmp_path: Path) -> None:
    seen_by_mode: dict[Mode, bool] = {}

    def retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        seen_by_mode[mode] = settings.rerank_enabled
        return FakeRetriever(mode=mode)

    client = _client(tmp_path, retriever_factory=retriever_factory)
    payload = _sample_payload(
        question_set=_adhoc_question_set(),
        combos=[
            _combo(
                "no-rerank",
                mode="dense",
                generation_provider=None,
                rerank_enabled=True,
                rerank_model_name="off",
            ),
            _combo("control", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    assert _count_events(events, "error") == 0
    assert seen_by_mode["dense"] is False


def test_benchmark_question_set_routes_to_per_benchmark_collection(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        qdrant_collection="sentinel-nq-coll-xyz",
    )
    _write_eval_questions(settings.output_dir / "eval_questions", count=1, benchmark="musique")
    _write_eval_questions(settings.output_dir / "eval_questions", count=1, benchmark="nq")
    calls: list[tuple[str, Mode]] = []

    def retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        calls.append((settings.qdrant_collection, mode))
        return FakeRetriever(mode=mode)

    client = _client(tmp_path, settings=settings, retriever_factory=retriever_factory)
    musique_payload = _sample_payload(
        question_set={
            "kind": "sample",
            "benchmark": "musique",
            "size": 1,
            "strategy": "first",
        },
        combos=[
            _combo("dense", mode="dense", generation_provider=None),
            _combo("sparse", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, musique_payload)

    assert response.status_code == 200
    assert _count_events(events, "error") == 0
    assert {collection for collection, _mode in calls} == {api_main.MUSIQUE_COLLECTION}

    calls.clear()
    nq_payload = _sample_payload(
        question_set={"kind": "sample", "benchmark": "nq", "size": 1, "strategy": "first"},
        combos=[
            _combo("dense", mode="dense", generation_provider=None),
            _combo("sparse", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, nq_payload)

    assert response.status_code == 200
    assert _count_events(events, "error") == 0
    assert {collection for collection, _mode in calls} == {"sentinel-nq-coll-xyz"}


def test_suite_benchmark_routes_to_suite_config_collection(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    suite_collection = "sentinel-suite-coll-2026"
    suite = _write_suite(
        settings.output_dir / "eval_suites",
        entry_count=1,
        benchmark="hotpotqa",
        collection=suite_collection,
    )
    calls: list[tuple[str, Mode]] = []

    def retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        calls.append((settings.qdrant_collection, mode))
        return FakeRetriever(mode=mode)

    client = _client(tmp_path, settings=settings, retriever_factory=retriever_factory)
    payload = _sample_payload(
        question_set={"kind": "suite", "suite_id": suite.id},
        combos=[
            _combo("dense", mode="dense", generation_provider=None),
            _combo("sparse", mode="sparse", generation_provider=None),
        ],
    )

    response, events = _post_stream(client, payload)

    assert response.status_code == 200
    assert _count_events(events, "error") == 0
    assert {collection for collection, _mode in calls} == {suite_collection}


def _post_stream(client: TestClient, payload: dict) -> tuple[object, list[tuple[str, dict]]]:
    with client.stream("POST", "/api/benchmark/stream", json=payload) as response:
        text = response.read().decode("utf-8")
    return response, _parse_events(text)


def _parse_events(text: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        lines = block.split("\n")
        event_line = next((line for line in lines if line.startswith("event:")), None)
        data_line = next((line for line in lines if line.startswith("data:")), None)
        if event_line and data_line:
            out.append(
                (
                    event_line[len("event:") :].strip(),
                    json.loads(data_line[len("data:") :].strip()),
                )
            )
    return out


def _client(
    tmp_path: Path,
    *,
    settings: Settings | None = None,
    sleep_seconds: float = 0.0,
    retriever_factory: Callable[[Settings, Mode], FakeRetriever] | None = None,
) -> TestClient:
    app = api_main.create_app(
        settings=settings or Settings(output_dir=tmp_path / "artifacts"),
        retriever_factory=retriever_factory
        or (lambda settings, mode: FakeRetriever(mode=mode, sleep_seconds=sleep_seconds)),
        generator_factory=lambda settings: FakeGenerator(),
    )
    return TestClient(app)


def _adhoc_payload() -> dict:
    return _sample_payload(question_set=_adhoc_question_set(), combos=_two_combos())


def _adhoc_question_set() -> dict:
    return {
        "kind": "adhoc",
        "benchmark": "nq",
        "query": "Question 0",
        "gold_answers": ["Answer for Question 0"],
        "supporting_passage_ids": ["support-0", "support-extra-0"],
    }


def _sample_payload(*, question_set: dict, combos: list[dict]) -> dict:
    return {"question_set": question_set, "combos": combos}


def _two_combos() -> list[dict]:
    return [
        _combo("dense", mode="dense"),
        _combo("sparse", mode="sparse"),
    ]


def _combo(
    combo_id: str,
    *,
    mode: Mode = "dense",
    generation_provider: str | None = "heuristic",
    retrieve_k: int | None = None,
    rerank_enabled: bool = False,
    rerank_model_name: str | None = None,
) -> dict:
    combo = {
        "id": combo_id,
        "mode": mode,
        "top_k": 2,
        "rerank_enabled": rerank_enabled,
    }
    if retrieve_k is not None:
        combo["retrieve_k"] = retrieve_k
    if rerank_model_name is not None:
        combo["rerank_model_name"] = rerank_model_name
    if generation_provider is not None:
        combo["generation_provider"] = generation_provider
    return combo


def _count_events(events: list[tuple[str, dict]], event_name: str) -> int:
    return sum(1 for event, _payload in events if event == event_name)


def _result_count_by_combo(result_events: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for payload in result_events:
        combo_id = payload["combo_id"]
        out[combo_id] = out.get(combo_id, 0) + 1
    return out


def _write_eval_questions(
    eval_questions_dir: Path, *, count: int, benchmark: str = "nq"
) -> None:
    eval_questions_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "query_id": f"{benchmark}-{i}",
            "query": f"Question {i}",
            "gold_answers": [f"Answer for Question {i}"],
            "supporting_passage_ids": [f"support-{i}", f"support-extra-{i}"],
        }
        for i in range(count)
    ]
    (eval_questions_dir / f"{benchmark}.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )


def _write_suite(
    suites_dir: Path,
    *,
    entry_count: int,
    benchmark: str = "nq",
    collection: str = "nq_passages_qwen3_embed_4b",
) -> EvalSuite:
    created_at = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    suite = EvalSuite(
        id="benchmark-suite",
        name="Benchmark Suite",
        description=None,
        created_at=created_at,
        updated_at=created_at,
        config=SuiteConfig(
            benchmark=benchmark,
            collection=collection,
            mode="hybrid",
            top_k=2,
            reranker="off",
            generator="heuristic",
        ),
        entries=[
            SuiteEntry(
                id=f"entry-{i}",
                question=f"Suite question {i}",
                gold_answers=[f"Answer for Suite question {i}"],
                source="authored",
            )
            for i in range(entry_count)
        ],
    )
    eval_suite.save_suite(suite, suites_dir)
    return suite


def _point_ids_for_query(query: str, mode: Mode) -> list[str]:
    del mode
    index = _query_index(query)
    if index == 0:
        return [f"support-{index}", "miss-0", f"support-extra-{index}"]
    if index == 1:
        return ["miss-1", f"support-{index}", "miss-1b"]
    return ["miss-2", "miss-2b", f"support-extra-{index}"]


def _query_index(query: str) -> int:
    last = query.rsplit(" ", maxsplit=1)[-1]
    return int(last) if last.isdigit() else 0


def _hit(point_id: str) -> PassageHit:
    return PassageHit(point_id=point_id, text=f"Evidence {point_id}")
