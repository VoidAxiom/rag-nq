from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.api.schemas import EvalQuestion
from src.config.settings import Settings
from src.ingestion.models import IndexChunk
from src.scripts.curate_eval_questions import curate


def test_curate_nq_from_index_chunks_is_deterministic(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    settings = Settings(output_dir=output_dir)
    _write_index_chunks(settings.index_chunks_path)

    first = curate("nq", sample_size=10, seed=123, output_dir=output_dir)
    second = curate("nq", sample_size=10, seed=123, output_dir=output_dir)

    assert len(first) >= 1
    assert first == second
    assert [question.query for question in first] == sorted(question.query for question in first)
    assert all(question.gold_answers for question in first)
    france = next(
        question for question in first if question.query == "What is France's capital?"
    )
    assert france.query_id == _stable_query_id("nq", france.query)
    assert france.gold_answers == ["Paris"]
    assert france.supporting_passage_ids == ["c-fr-1", "c-fr-2"]
    written = TypeAdapter(list[EvalQuestion]).validate_json(
        (output_dir / "eval_questions" / "nq.json").read_bytes()
    )
    assert written == first


@pytest.mark.parametrize("benchmark", ["hotpotqa", "2wikimhqa"])
def test_curate_rejects_empty_collection_benchmarks(
    tmp_path: Path, benchmark: str
) -> None:
    with pytest.raises(ValueError, match="empty by design"):
        curate(benchmark, sample_size=1, seed=0, output_dir=tmp_path / "artifacts")


def _write_index_chunks(path: Path) -> None:
    chunks = [
        IndexChunk(
            chunk_id="c-fr-2",
            group_id="g-fr",
            text="Paris has many museums.",
            context_text="France facts mention Paris as the capital.",
            source_row_ordinal=1,
            start_candidate_idx=2,
            end_candidate_idx=2,
            question="What is France's capital?",
            long_answers=["Paris"],
        ),
        IndexChunk(
            chunk_id="c-fr-x",
            group_id="g-fr",
            text="Madrid is the capital of Spain.",
            context_text="Spain facts.",
            source_row_ordinal=1,
            start_candidate_idx=3,
            end_candidate_idx=3,
            question="What is France's capital?",
            long_answers=["Paris"],
        ),
        IndexChunk(
            chunk_id="c-de-1",
            group_id="g-de",
            text="Berlin is the capital of Germany.",
            context_text="Berlin appears in the answer sentence.",
            source_row_ordinal=2,
            start_candidate_idx=1,
            end_candidate_idx=1,
            question="What is Germany's capital?",
            long_answers=["Berlin"],
        ),
        IndexChunk(
            chunk_id="c-fr-1",
            group_id="g-fr",
            text="The capital of France is Paris.",
            context_text="Paris is the answer.",
            source_row_ordinal=1,
            start_candidate_idx=1,
            end_candidate_idx=1,
            question="What is France's capital?",
            long_answers=["Paris"],
        ),
        IndexChunk(
            chunk_id="c-sky-1",
            group_id="g-sky",
            text="The daytime sky is blue.",
            context_text="Blue is a color.",
            source_row_ordinal=3,
            start_candidate_idx=1,
            end_candidate_idx=1,
            question="What color is the daytime sky?",
            long_answers=["Blue"],
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(chunk.model_dump_json() for chunk in chunks) + "\n",
        encoding="utf-8",
    )


def _stable_query_id(benchmark: str, query: str) -> str:
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]
    return f"{benchmark}-{digest}"
