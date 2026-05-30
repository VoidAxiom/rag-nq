from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api.schemas import BenchmarkComboSettings, BenchmarkSampleQuestion
from src.config.settings import Settings
from src.evaluation.benchmark_runner import (
    ComboRunResult,
    PerQuestionMetricValues,
    QuestionInput,
    compute_running_aggregates,
    load_eval_questions,
    resolve_questions,
    run_single_question,
    settings_for_combo,
)
from src.evaluation.per_query_metrics import compute_em, compute_f1
from src.evaluation.retrieval_eval import (
    compute_mrr_at_k,
    compute_ndcg_at_k,
    compute_recall_at_k,
)
from src.models.query_schemas import GroundedAnswer, LatencyBreakdown, PassageHit, RetrievalMetrics


class FakeRetriever:
    def __init__(self) -> None:
        self.last_retrieval_metrics = RetrievalMetrics()
        self.requested_top_k: int | None = None

    def retrieve_with_metrics(
        self, query: str, top_k: int
    ) -> tuple[list[PassageHit], RetrievalMetrics | None]:
        del query
        self.requested_top_k = top_k
        return (
            [
                _hit("p1"),
                _hit("p2"),
                _hit("p3"),
                _hit("p4"),
            ],
            self.last_retrieval_metrics,
        )


class FakeGenerator:
    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer:
        del query, hits
        return GroundedAnswer(answer="Paris", abstained=False)


def test_compute_running_aggregates_over_fixed_results_with_nulls() -> None:
    results = [
        _result(
            metrics=PerQuestionMetricValues(
                recall_at_1=1.0,
                recall_at_5=1.0,
                recall_at_10=1.0,
                mrr_at_10=1.0,
                ndcg_at_10=None,
                em=1.0,
                f1=1.0,
            ),
            latency=LatencyBreakdown(
                retrieval_ms=10.0,
                rerank_ms=1.0,
                generation_ms=5.0,
                total_ms=16.0,
            ),
        ),
        _result(
            metrics=PerQuestionMetricValues(
                recall_at_1=0.0,
                recall_at_5=None,
                recall_at_10=0.5,
                mrr_at_10=None,
                ndcg_at_10=None,
                em=None,
                f1=0.5,
            ),
            latency=LatencyBreakdown(
                retrieval_ms=20.0,
                rerank_ms=2.0,
                generation_ms=0.0,
                total_ms=22.0,
            ),
        ),
        _result(
            metrics=PerQuestionMetricValues(
                recall_at_1=None,
                recall_at_5=0.5,
                recall_at_10=None,
                mrr_at_10=0.25,
                ndcg_at_10=None,
                em=0.0,
                f1=None,
            ),
            latency=LatencyBreakdown(
                retrieval_ms=30.0,
                rerank_ms=3.0,
                generation_ms=10.0,
                total_ms=43.0,
            ),
        ),
    ]

    aggregates = compute_running_aggregates(results)

    assert aggregates["recall_at_1_mean"] == pytest.approx((1.0 + 0.0) / 2.0)
    assert aggregates["recall_at_5_mean"] == pytest.approx((1.0 + 0.5) / 2.0)
    assert aggregates["recall_at_10_mean"] == pytest.approx((1.0 + 0.5) / 2.0)
    assert aggregates["mrr_at_10_mean"] == pytest.approx((1.0 + 0.25) / 2.0)
    assert aggregates["ndcg_at_10_mean"] is None
    assert aggregates["em_mean"] == pytest.approx((1.0 + 0.0) / 2.0)
    assert aggregates["f1_mean"] == pytest.approx((1.0 + 0.5) / 2.0)
    assert aggregates["retrieval_ms_mean"] == pytest.approx((10.0 + 20.0 + 30.0) / 3.0)
    assert aggregates["rerank_ms_mean"] == pytest.approx((1.0 + 2.0 + 3.0) / 3.0)
    assert aggregates["generation_ms_mean"] == pytest.approx((5.0 + 0.0 + 10.0) / 3.0)
    assert aggregates["total_ms_mean"] == pytest.approx((16.0 + 22.0 + 43.0) / 3.0)


def test_run_single_question_end_to_end_with_mocked_factories() -> None:
    fake_retriever = FakeRetriever()
    combo = BenchmarkComboSettings(
        id="dense-heuristic",
        mode="dense",
        top_k=2,
        generation_provider="heuristic",
    )
    question = QuestionInput(
        query="What is the capital of France?",
        benchmark="nq",
        gold_answers=("Paris",),
        supporting_passage_ids=("p1", "p3"),
    )

    result = run_single_question(
        combo=combo,
        settings=Settings(),
        question=question,
        question_index=0,
        retriever_factory=lambda settings, mode: fake_retriever,
        generator_factory=lambda settings: FakeGenerator(),
    )

    retrieved_ids = ["p1", "p2", "p3", "p4"]
    relevant_ids = {"p1", "p3"}
    assert fake_retriever.requested_top_k == 10
    assert [hit.point_id for hit in result.retrieved_passages] == ["p1", "p2"]
    assert result.metrics.recall_at_1 == compute_recall_at_k(
        retrieved_ids, relevant_ids, k=1
    )
    assert result.metrics.recall_at_5 == compute_recall_at_k(
        retrieved_ids, relevant_ids, k=5
    )
    assert result.metrics.recall_at_10 == compute_recall_at_k(
        retrieved_ids, relevant_ids, k=10
    )
    assert result.metrics.mrr_at_10 == compute_mrr_at_k(retrieved_ids, relevant_ids, k=10)
    assert result.metrics.ndcg_at_10 == compute_ndcg_at_k(
        retrieved_ids, relevant_ids, k=10
    )
    assert result.metrics.em == compute_em("Paris", ["Paris"])
    assert result.metrics.f1 == compute_f1("Paris", ["Paris"])


def test_sample_random_seed_is_deterministic_across_seeds(tmp_path: Path) -> None:
    eval_questions_dir = _write_eval_questions(tmp_path)
    qset_a = BenchmarkSampleQuestion(
        kind="sample", benchmark="nq", size=5, strategy="random", seed=7
    )
    qset_b = BenchmarkSampleQuestion(
        kind="sample", benchmark="nq", size=5, strategy="random", seed=7
    )
    qset_c = BenchmarkSampleQuestion(
        kind="sample", benchmark="nq", size=5, strategy="random", seed=11
    )

    first = resolve_questions(
        qset_a,
        suite_loader=lambda suite_id: None,
        eval_questions_loader=lambda benchmark: load_eval_questions(
            benchmark, eval_questions_dir=eval_questions_dir
        ),
    )
    second = resolve_questions(
        qset_b,
        suite_loader=lambda suite_id: None,
        eval_questions_loader=lambda benchmark: load_eval_questions(
            benchmark, eval_questions_dir=eval_questions_dir
        ),
    )
    third = resolve_questions(
        qset_c,
        suite_loader=lambda suite_id: None,
        eval_questions_loader=lambda benchmark: load_eval_questions(
            benchmark, eval_questions_dir=eval_questions_dir
        ),
    )

    assert [q.query for q in first.questions] == [q.query for q in second.questions]
    assert [q.query for q in first.questions] != [q.query for q in third.questions]


def test_sample_first_returns_first_n_in_file_order(tmp_path: Path) -> None:
    eval_questions_dir = _write_eval_questions(tmp_path)
    qset = BenchmarkSampleQuestion(kind="sample", benchmark="nq", size=3, strategy="first")

    resolved = resolve_questions(
        qset,
        suite_loader=lambda suite_id: None,
        eval_questions_loader=lambda benchmark: load_eval_questions(
            benchmark, eval_questions_dir=eval_questions_dir
        ),
    )

    assert [q.query for q in resolved.questions] == [
        "Question 0",
        "Question 1",
        "Question 2",
    ]


def test_settings_for_combo_rerank_off_disables_rerank_flag() -> None:
    result = settings_for_combo(
        Settings(),
        BenchmarkComboSettings(
            id="x",
            mode="dense",
            top_k=5,
            rerank_enabled=True,
            rerank_model_name="off",
        ),
    )

    assert result.rerank_enabled is False


def test_settings_for_combo_propagates_retrieve_k_override() -> None:
    result = settings_for_combo(
        Settings(),
        BenchmarkComboSettings(
            id="x",
            mode="dense",
            top_k=5,
            retrieve_k=77,
        ),
    )

    assert result.retrieve_k == 77


def test_settings_for_combo_openai_provider_applies_auto_defaults() -> None:
    result = settings_for_combo(
        Settings(),
        BenchmarkComboSettings(
            id="c",
            mode="dense",
            top_k=5,
            generation_provider="openai",
        ),
    )

    assert result.generation_model_name == "gpt-4o"
    assert result.generation_api_key_env == "RAG_OPENAI_API_KEY"
    assert result.generation_api_url is None


def test_settings_for_combo_openai_with_explicit_model_name_wins() -> None:
    result = settings_for_combo(
        Settings(),
        BenchmarkComboSettings(
            id="c",
            mode="dense",
            top_k=5,
            generation_provider="openai",
            generation_model_name="gpt-4o-mini",
        ),
    )

    assert result.generation_model_name == "gpt-4o-mini"


def _hit(point_id: str) -> PassageHit:
    return PassageHit(point_id=point_id, text=f"Evidence {point_id}")


def _result(
    *,
    metrics: PerQuestionMetricValues,
    latency: LatencyBreakdown,
) -> ComboRunResult:
    return ComboRunResult(
        combo_id="combo-a",
        question_index=0,
        query="Question",
        grounded=None,
        retrieved_passages=[],
        metrics=metrics,
        latency_ms=latency,
    )


def _write_eval_questions(tmp_path: Path) -> Path:
    eval_questions_dir = tmp_path / "eval_questions"
    eval_questions_dir.mkdir()
    rows = [
        {
            "query_id": f"nq-{i}",
            "query": f"Question {i}",
            "gold_answers": [f"Answer {i}"],
            "supporting_passage_ids": [f"support-{i}"],
        }
        for i in range(10)
    ]
    (eval_questions_dir / "nq.json").write_text(json.dumps(rows), encoding="utf-8")
    return eval_questions_dir
