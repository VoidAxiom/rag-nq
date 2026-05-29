from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config.settings import Settings
from src.evaluation.eval_suite import DatasetRef, EvalSuite, SuiteConfig, SuiteEntry
from src.evaluation.eval_suite_runner import EvalSuiteRunResult, run_suite
from src.models.query_schemas import Citation, GroundedAnswer, PassageHit, RetrievalMetrics
from src.retrieval.qdrant_retrievers import Mode


class FakeRetriever:
    def __init__(self, hits_by_query: dict[str, list[str]]) -> None:
        self.hits_by_query = hits_by_query
        self.last_retrieval_metrics = RetrievalMetrics()
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, top_k: int) -> list[PassageHit]:
        self.calls.append((query, top_k))
        return [
            PassageHit(point_id=point_id, text=f"Evidence {point_id}")
            for point_id in self.hits_by_query[query][:top_k]
        ]


class FakeGenerator:
    def __init__(self, answers_by_query: dict[str, str]) -> None:
        self.answers_by_query = answers_by_query
        self.calls: list[str] = []
        self.hits_received: list[int] = []

    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer:
        self.calls.append(query)
        self.hits_received.append(len(hits))
        return GroundedAnswer(
            answer=self.answers_by_query[query],
            citations=[Citation(point_id=hits[0].point_id)] if hits else [],
            abstained=False,
            supporting_point_ids=[hits[0].point_id] if hits else [],
            supporting_evidence=hits[:1],
        )


def test_run_suite_aggregates_retrieval_answer_latency_and_provenance(
    tmp_path: Path,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts", embedder_name="embedder-test")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1", "p3"],
                    "notes": None,
                },
                {
                    "query_id": "q2",
                    "query": "Question two?",
                    "gold_answers": ["Lyon"],
                    "supporting_passage_ids": ["p9"],
                    "notes": None,
                },
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            ),
            _entry(
                "e2",
                question="Question two?",
                gold_answers=["Lyon"],
                question_id="q2",
            ),
            SuiteEntry(
                id="e3",
                question="Authored?",
                gold_answers=["Rome"],
                source="authored",
                dataset_ref=None,
            ),
        ]
    )
    retriever = FakeRetriever(
        {
            "Question one?": ["p1", "x", "p3"],
            "Question two?": ["x", "y", "p9"],
            "Authored?": ["a1"],
        }
    )
    generator = FakeGenerator(
        {
            "Question one?": "Paris",
            "Question two?": "wrong",
            "Authored?": "Rome",
        }
    )
    progress: list[int] = []
    captured: dict[str, object] = {}

    def retriever_factory(factory_settings: Settings, mode: Mode) -> FakeRetriever:
        captured["retriever_settings"] = factory_settings
        captured["mode"] = mode
        return retriever

    def generator_factory(factory_settings: Settings) -> FakeGenerator:
        captured["generator_settings"] = factory_settings
        return generator

    result = run_suite(
        suite,
        app_settings=settings,
        retriever_factory=retriever_factory,
        generator_factory=generator_factory,
        launched_via="cli",
        run_id="run-1",
        progress_cb=progress.append,
        commit_sha="abc123",
    )

    assert progress == [1, 2, 3]
    assert retriever.calls == [
        ("Question one?", 10),
        ("Question two?", 10),
        ("Authored?", 10),
    ]
    assert generator.calls == ["Question one?", "Question two?", "Authored?"]
    assert captured["mode"] == "hybrid"
    retriever_settings = captured["retriever_settings"]
    assert isinstance(retriever_settings, Settings)
    assert retriever_settings.qdrant_collection == "suite-collection"
    assert retriever_settings.rerank_enabled is True
    assert retriever_settings.rerank_model_name == "reranker-test"

    row = result.row
    assert row.phase == "suite"
    assert row.pipeline == "hybrid+rerank"
    assert row.benchmark == "nq"
    assert row.split == "mixed"
    assert row.commit_sha == "abc123"
    assert row.suite_id == "suite-1"
    assert row.suite_name == "Suite One"
    assert row.run_id == "run-1"
    assert row.num_questions == 3
    assert row.launched_via == "cli"
    assert row.models.embedder == "embedder-test"
    assert row.models.reranker == "reranker-test"

    # Retrieval rows:
    # e1 support={p1,p3}, hits [p1,x,p3]:
    #   r@1=1/2, r@5=2/2, r@10=2/2, mrr=1, ndcg=(1+1/log2(4))/(1+1/log2(3)).
    # e2 support={p9}, hits [x,y,p9]:
    #   r@1=0, r@5=1, r@10=1, mrr=1/3, ndcg=(1/log2(4))/1.
    rm = row.retriever_metrics
    assert rm.recall_at_1 == pytest.approx((0.5 + 0.0) / 2.0)
    assert rm.recall_at_5 == pytest.approx(1.0)
    assert rm.recall_at_10 == pytest.approx(1.0)
    assert rm.mrr_at_10 == pytest.approx((1.0 + (1.0 / 3.0)) / 2.0)
    assert rm.ndcg_at_10 == pytest.approx(
        (((1.0 + (1.0 / 2.0)) / (1.0 + (1.0 / 1.584962500721156))) + 0.5)
        / 2.0
    )

    # Answer rows: e1 EM/F1=1/1, e2=0/0, authored e3=1/1.
    # joint_f1 is mean(em*f1), not mean(em)*mean(f1): (1 + 0 + 1) / 3.
    am = row.answer_metrics
    assert am is not None
    assert am.em == pytest.approx(2.0 / 3.0)
    assert am.f1 == pytest.approx(2.0 / 3.0)
    assert am.joint_f1 == pytest.approx(2.0 / 3.0)
    assert row.latency_ms.p50 >= 0
    assert row.latency_ms.p95 >= 0
    assert [entry.entry_id for entry in result.per_entry] == ["e1", "e2", "e3"]
    assert result.per_entry[0].recall_at_5 == pytest.approx(1.0)
    assert result.per_entry[2].recall_at_5 is None


def test_run_suite_generator_off_omits_answer_metrics(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        config=_config(reranker="off", generator="off", mode="dense"),
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            )
        ],
    )
    retriever = FakeRetriever({"Question one?": ["p1"]})
    generator = FakeGenerator({"Question one?": "Paris"})

    result = run_suite(
        suite,
        app_settings=settings,
        retriever_factory=lambda settings, mode: retriever,
        generator_factory=lambda settings: generator,
        launched_via="ui",
        run_id="run-1",
        commit_sha="abc123",
    )

    assert result.row.pipeline == "dense"
    assert result.row.answer_metrics is None
    assert generator.calls == []


def test_run_suite_overlays_generator_onto_settings(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        config=_config(generator="http_json"),
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            )
        ],
    )
    retriever = FakeRetriever({"Question one?": ["p1"]})
    generator = FakeGenerator({"Question one?": "Paris"})
    captured: dict[str, Settings] = {}

    def generator_factory(factory_settings: Settings) -> FakeGenerator:
        captured["settings"] = factory_settings
        return generator

    run_suite(
        suite,
        app_settings=settings,
        retriever_factory=lambda settings, mode: retriever,
        generator_factory=generator_factory,
        launched_via="cli",
        run_id="run-1",
        commit_sha="abc123",
    )

    assert captured["settings"].generation_provider == "http_json"


def test_run_suite_split_is_dev_for_all_dataset_suite(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            )
        ],
    )
    retriever = FakeRetriever({"Question one?": ["p1"]})
    generator = FakeGenerator({"Question one?": "Paris"})

    result = run_suite(
        suite,
        app_settings=settings,
        retriever_factory=lambda settings, mode: retriever,
        generator_factory=lambda settings: generator,
        launched_via="cli",
        run_id="run-1",
        commit_sha="abc123",
    )

    assert result.row.split == "dev"


def test_run_suite_rejects_unknown_generator_via_pydantic_literal(
    tmp_path: Path,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        config=_config(generator="definitely-not-a-real-provider"),
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            )
        ],
    )
    retriever = FakeRetriever({"Question one?": ["p1"]})
    generator = FakeGenerator({"Question one?": "Paris"})

    with pytest.raises(ValidationError) as exc_info:
        run_suite(
            suite,
            app_settings=settings,
            retriever_factory=lambda settings, mode: retriever,
            generator_factory=lambda settings: generator,
            launched_via="cli",
            run_id="run-1",
            commit_sha="abc123",
        )

    assert "generation_provider" in str(exc_info.value).lower()


def test_run_suite_rejects_empty_or_authored_only_suite(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")

    with pytest.raises(ValueError, match="suite has no entries"):
        run_suite(
            _suite(entries=[]),
            app_settings=settings,
            retriever_factory=lambda settings, mode: FakeRetriever({}),
            generator_factory=lambda settings: FakeGenerator({}),
            launched_via="cli",
            run_id="run-1",
            commit_sha="abc123",
        )

    authored = _suite(
        entries=[
            SuiteEntry(
                id="e1",
                question="Authored?",
                gold_answers=["Rome"],
                source="authored",
                dataset_ref=None,
            )
        ]
    )
    with pytest.raises(ValueError, match="supporting-passage gold"):
        run_suite(
            authored,
            app_settings=settings,
            retriever_factory=lambda settings, mode: FakeRetriever({"Authored?": ["p1"]}),
            generator_factory=lambda settings: FakeGenerator({"Authored?": "Rome"}),
            launched_via="cli",
            run_id="run-2",
            commit_sha="abc123",
        )


def test_run_suite_retrieves_at_least_ten_hits_for_top_k_below_ten(
    tmp_path: Path,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1", "p2", "p3"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        config=_config(top_k=5),
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            )
        ],
    )
    retriever = FakeRetriever(
        {"Question one?": ["p1", "x1", "x2", "x3", "x4", "p2", "p3", "x5", "x6", "x7"]}
    )
    generator = FakeGenerator({"Question one?": "Paris"})

    result = run_suite(
        suite,
        app_settings=settings,
        retriever_factory=lambda settings, mode: retriever,
        generator_factory=lambda settings: generator,
        launched_via="cli",
        run_id="run-1",
        commit_sha="abc123",
    )

    assert retriever.calls[0][1] == 10
    assert generator.hits_received == [5]
    assert result.row.retriever_metrics.recall_at_10 == pytest.approx(1.0)
    assert result.row.retriever_metrics.recall_at_5 == pytest.approx(1.0 / 3.0)


def test_run_suite_uses_top_k_when_above_ten(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p5"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        config=_config(top_k=20),
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            )
        ],
    )
    retriever = FakeRetriever(
        {"Question one?": [f"p{index}" for index in range(1, 21)]}
    )
    generator = FakeGenerator({"Question one?": "Paris"})

    run_suite(
        suite,
        app_settings=settings,
        retriever_factory=lambda settings, mode: retriever,
        generator_factory=lambda settings: generator,
        launched_via="cli",
        run_id="run-1",
        commit_sha="abc123",
    )

    assert retriever.calls[0][1] == 20
    assert generator.hits_received == [20]


def test_run_suite_top_k_equals_ten_no_inflation(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        config=_config(top_k=10),
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            )
        ],
    )
    retriever = FakeRetriever(
        {"Question one?": ["x1", "x2", "x3", "x4", "p1", "x5", "x6", "x7", "x8", "x9"]}
    )
    generator = FakeGenerator({"Question one?": "Paris"})

    run_suite(
        suite,
        app_settings=settings,
        retriever_factory=lambda settings, mode: retriever,
        generator_factory=lambda settings: generator,
        launched_via="cli",
        run_id="run-1",
        commit_sha="abc123",
    )

    assert retriever.calls[0][1] == 10
    assert generator.hits_received == [10]


def test_pipeline_label_dense_with_reranker_is_just_dense(tmp_path: Path) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="dense", reranker="reranker-x"),
    )

    assert result.row.pipeline == "dense"


def test_pipeline_label_sparse_with_reranker_is_just_sparse(tmp_path: Path) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="sparse", reranker="reranker-x"),
    )

    assert result.row.pipeline == "sparse"


def test_pipeline_label_hybrid_off_is_just_hybrid(tmp_path: Path) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="hybrid", reranker="off"),
    )

    assert result.row.pipeline == "hybrid"


def test_pipeline_label_hybrid_with_reranker_is_hybrid_plus_rerank(
    tmp_path: Path,
) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="hybrid", reranker="reranker-x"),
    )

    assert result.row.pipeline == "hybrid+rerank"


def test_models_reranker_dense_is_off_even_when_configured(tmp_path: Path) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="dense", reranker="my-reranker"),
    )

    assert result.row.models.reranker == "off"


def test_models_reranker_sparse_is_off_even_when_configured(tmp_path: Path) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="sparse", reranker="my-reranker"),
    )

    assert result.row.models.reranker == "off"


def test_models_reranker_hybrid_off_is_off(tmp_path: Path) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="hybrid", reranker="off"),
    )

    assert result.row.models.reranker == "off"


def test_models_reranker_hybrid_on_reflects_config(tmp_path: Path) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="hybrid", reranker="my-reranker"),
    )

    assert result.row.models.reranker == "my-reranker"


def test_models_reasoning_llm_heuristic_is_none(tmp_path: Path) -> None:
    result = _run_single_entry_suite(
        tmp_path,
        config=_config(generator="heuristic"),
    )

    assert result.row.models.reasoning_llm is None


def test_models_reasoning_llm_generator_off_is_none(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        embedder_name="embedder-test",
        generation_model_name="some-label",
    )

    result = _run_single_entry_suite(
        tmp_path,
        config=_config(mode="dense", reranker="off", generator="off"),
        settings=settings,
    )

    assert result.row.models.reasoning_llm is None


def test_models_reasoning_llm_openai_uses_generation_model_name(
    tmp_path: Path,
) -> None:
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        embedder_name="embedder-test",
        generation_model_name="gpt-4o-mini",
    )

    result = _run_single_entry_suite(
        tmp_path,
        config=_config(generator="openai"),
        settings=settings,
    )

    assert result.row.models.reasoning_llm == "gpt-4o-mini"


def test_models_reasoning_llm_openai_falls_back_to_provider_when_model_name_empty(
    tmp_path: Path,
) -> None:
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        embedder_name="embedder-test",
        generation_model_name="",
    )

    result = _run_single_entry_suite(
        tmp_path,
        config=_config(generator="openai"),
        settings=settings,
    )

    assert result.row.models.reasoning_llm == "openai"


def test_models_reasoning_llm_http_json_uses_generation_model_name(
    tmp_path: Path,
) -> None:
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        embedder_name="embedder-test",
        generation_model_name="some-model",
    )

    result = _run_single_entry_suite(
        tmp_path,
        config=_config(generator="http_json"),
        settings=settings,
    )

    assert result.row.models.reasoning_llm == "some-model"


def _run_single_entry_suite(
    tmp_path: Path,
    *,
    config: SuiteConfig,
    settings: Settings | None = None,
) -> EvalSuiteRunResult:
    if settings is None:
        settings = Settings(output_dir=tmp_path / "artifacts")
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "Question one?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    suite = _suite(
        config=config,
        entries=[
            _entry(
                "e1",
                question="Question one?",
                gold_answers=["Paris"],
                question_id="q1",
            )
        ],
    )
    retriever = FakeRetriever({"Question one?": ["p1"]})
    generator = FakeGenerator({"Question one?": "Paris"})

    return run_suite(
        suite,
        app_settings=settings,
        retriever_factory=lambda settings, mode: retriever,
        generator_factory=lambda settings: generator,
        launched_via="cli",
        run_id="run-1",
        commit_sha="abc123",
    )


def _suite(
    *,
    config: SuiteConfig | None = None,
    entries: list[SuiteEntry],
) -> EvalSuite:
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return EvalSuite(
        id="suite-1",
        name="Suite One",
        description=None,
        created_at=now,
        updated_at=now,
        config=config or _config(),
        entries=entries,
    )


def _config(
    *,
    reranker: str = "reranker-test",
    generator: str = "heuristic",
    mode: Mode = "hybrid",
    top_k: int = 10,
) -> SuiteConfig:
    return SuiteConfig(
        benchmark="nq",
        collection="suite-collection",
        mode=mode,
        top_k=top_k,
        reranker=reranker,
        generator=generator,
    )


def _entry(
    entry_id: str,
    *,
    question: str,
    gold_answers: list[str],
    question_id: str,
) -> SuiteEntry:
    return SuiteEntry(
        id=entry_id,
        question=question,
        gold_answers=gold_answers,
        source="dataset",
        dataset_ref=DatasetRef(benchmark="nq", question_id=question_id),
    )
