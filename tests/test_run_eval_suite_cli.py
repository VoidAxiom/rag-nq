from __future__ import annotations

import datetime
import json
from pathlib import Path

from src.evaluation import eval_suite
from src.evaluation.eval_suite import DatasetRef, EvalSuite, SuiteConfig, SuiteEntry
from src.evaluation.scoreboard import load_scoreboard
from src.models.query_schemas import Citation, GroundedAnswer, PassageHit, RetrievalMetrics
from src.scripts import run_eval_suite


class FakeRetriever:
    last_retrieval_metrics = RetrievalMetrics()

    def retrieve(self, query: str, top_k: int) -> list[PassageHit]:
        del query, top_k
        return [PassageHit(point_id="p1", text="Evidence p1")]


class FakeGenerator:
    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer:
        del query
        return GroundedAnswer(
            answer="Paris",
            citations=[Citation(point_id=hits[0].point_id)],
            abstained=False,
            supporting_point_ids=[hits[0].point_id],
            supporting_evidence=hits[:1],
        )


def test_cli_runs_suite_by_id_and_writes_scoreboard_row(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    output_dir = tmp_path / "artifacts"
    _write_eval_question(output_dir)
    suite = _suite("suite-1", name="NQ Smoke Suite")
    eval_suite.save_suite(suite, output_dir / "eval_suites")
    monkeypatch.setattr(
        run_eval_suite,
        "_default_retriever_factory",
        lambda settings, mode: FakeRetriever(),
    )
    monkeypatch.setattr(
        run_eval_suite,
        "_default_generator_factory",
        lambda settings: FakeGenerator(),
    )
    monkeypatch.setattr(run_eval_suite, "uuid4", lambda: type("Uuid", (), {"hex": "run-1"})())

    exit_code = run_eval_suite.main(
        ["--suite", "suite-1", "--output-dir", str(output_dir)]
    )

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "Suite: NQ Smoke Suite (suite-1)" in stdout
    assert "Wrote scoreboard row id=run-1 launched_via=cli" in stdout
    scoreboard = load_scoreboard(output_dir / "scoreboard.json")
    assert len(scoreboard.rows) == 1
    row = scoreboard.rows[0]
    assert row.suite_id == "suite-1"
    assert row.suite_name == "NQ Smoke Suite"
    assert row.run_id == "run-1"
    assert row.launched_via == "cli"
    assert row.retriever_metrics.recall_at_5 == 1.0


def test_cli_resolves_suite_by_unique_name(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "artifacts"
    _write_eval_question(output_dir)
    eval_suite.save_suite(
        _suite("suite-1", name="NQ Smoke Suite"), output_dir / "eval_suites"
    )
    monkeypatch.setattr(
        run_eval_suite,
        "_default_retriever_factory",
        lambda settings, mode: FakeRetriever(),
    )
    monkeypatch.setattr(
        run_eval_suite,
        "_default_generator_factory",
        lambda settings: FakeGenerator(),
    )

    exit_code = run_eval_suite.main(
        ["--suite", "nq smoke suite", "--output-dir", str(output_dir)]
    )

    assert exit_code == 0
    assert len(load_scoreboard(output_dir / "scoreboard.json").rows) == 1


def test_cli_returns_one_for_missing_or_ambiguous_suite(tmp_path: Path, capsys) -> None:
    output_dir = tmp_path / "artifacts"

    missing_code = run_eval_suite.main(
        ["--suite", "missing", "--output-dir", str(output_dir)]
    )

    assert missing_code == 1
    assert "no suite found" in capsys.readouterr().err

    eval_suite.save_suite(_suite("suite-a", name="Same"), output_dir / "eval_suites")
    eval_suite.save_suite(_suite("suite-b", name="Same"), output_dir / "eval_suites")

    ambiguous_code = run_eval_suite.main(
        ["--suite", "same", "--output-dir", str(output_dir)]
    )

    assert ambiguous_code == 1
    assert "ambiguous suite name" in capsys.readouterr().err


def _write_eval_question(output_dir: Path) -> None:
    eval_questions_dir = output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "What is the capital of France?",
                    "gold_answers": ["Paris"],
                    "supporting_passage_ids": ["p1"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )


def _suite(suite_id: str, *, name: str) -> EvalSuite:
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return EvalSuite(
        id=suite_id,
        name=name,
        description=None,
        created_at=now,
        updated_at=now,
        config=SuiteConfig(
            benchmark="nq",
            collection="nq_passages_qwen3_embed_4b",
            mode="hybrid",
            top_k=5,
            reranker="off",
            generator="heuristic",
        ),
        entries=[
            SuiteEntry(
                id="entry-1",
                question="What is the capital of France?",
                gold_answers=["Paris"],
                source="dataset",
                dataset_ref=DatasetRef(benchmark="nq", question_id="q1"),
            )
        ],
    )
