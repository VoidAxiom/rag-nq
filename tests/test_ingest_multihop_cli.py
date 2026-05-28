from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.config.settings import Settings
from src.ingestion.models import IndexChunk, Passage
from src.ingestion.multihop_loader import MultihopBenchmark
from src.retrieval.dense_index import DenseBuildResult
from src.retrieval.sparse_qdrant import SparseQdrantBuildResult
from src.scripts import ingest_multihop


@dataclass(slots=True)
class _StubLoader:
    benchmark: MultihopBenchmark
    passages: Sequence[Passage]
    expected_count: int

    @property
    def dataset_name(self) -> str:
        return self.benchmark.value

    @property
    def expected_collection_name(self) -> str:
        return f"{self.benchmark.value}_passages_qwen3_embed_4b"

    @property
    def expected_passage_count(self) -> int:
        return self.expected_count

    def iter_passages(self) -> Iterator[Passage]:
        yield from self.passages


def _make_passages(count: int, *, prefix: str = "p") -> list[Passage]:
    return [
        Passage(
            passage_id=f"{prefix}-{ordinal}",
            text=f"text {ordinal}",
            title=f"title {ordinal}",
            source=f"source {ordinal}",
            question=f"question {ordinal}?",
            document_url=f"https://example.test/{prefix}/{ordinal}",
            long_answers=[f"answer {ordinal}"],
        )
        for ordinal in range(count)
    ]


def _patch_loader(
    monkeypatch: pytest.MonkeyPatch,
    *,
    benchmark: MultihopBenchmark = MultihopBenchmark.MUSIQUE,
    passages: Sequence[Passage],
    expected_count: int,
) -> list[MultihopBenchmark]:
    calls: list[MultihopBenchmark] = []

    def fake_load_multihop(name: MultihopBenchmark) -> _StubLoader:
        calls.append(name)
        return _StubLoader(
            benchmark=benchmark,
            passages=passages,
            expected_count=expected_count,
        )

    monkeypatch.setattr(ingest_multihop, "load_multihop", fake_load_multihop)
    return calls


def _run_dry_ingest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    actual_count: int,
    expected_count: int,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    passages = _make_passages(actual_count, prefix="ratio")
    _patch_loader(monkeypatch, passages=passages, expected_count=expected_count)
    ingest_multihop.main(["--dataset", "musique", "--dry-run"])


@pytest.mark.parametrize(
    ("dataset_arg", "expected_benchmark"),
    [
        ("hotpotqa", MultihopBenchmark.HOTPOTQA),
        ("2wikimhqa", MultihopBenchmark.TWOWIKIMHQA),
        ("musique", MultihopBenchmark.MUSIQUE),
    ],
)
def test_dataset_argument_dispatches_to_correct_benchmark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dataset_arg: str,
    expected_benchmark: MultihopBenchmark,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    calls = _patch_loader(
        monkeypatch,
        benchmark=expected_benchmark,
        passages=_make_passages(2, prefix=dataset_arg),
        expected_count=2,
    )

    ingest_multihop.main(["--dataset", dataset_arg, "--dry-run"])

    assert calls == [expected_benchmark]


def test_jsonl_written_at_per_benchmark_path_with_index_chunk_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    passages = _make_passages(3, prefix="synthetic")
    _patch_loader(monkeypatch, passages=passages, expected_count=3)

    ingest_multihop.main(["--dataset", "musique", "--dry-run"])

    jsonl_path = tmp_path / "multihop_passages__musique.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3

    objects = [json.loads(line) for line in lines]
    required_keys = {
        "chunk_id",
        "group_id",
        "text",
        "context_text",
        "source_row_ordinal",
        "chunk_kind",
    }
    for obj in objects:
        assert required_keys <= set(obj)
    expected_chunk_ids = [
        ingest_multihop._multihop_point_id(f"synthetic-{i}") for i in range(3)
    ]
    assert [obj["chunk_id"] for obj in objects] == expected_chunk_ids
    assert [obj["group_id"] for obj in objects] == [
        "synthetic-0",
        "synthetic-1",
        "synthetic-2",
    ]
    assert [obj["source_row_ordinal"] for obj in objects] == [0, 1, 2]
    for obj in objects:
        uuid.UUID(obj["chunk_id"])
    for line in lines:
        IndexChunk.model_validate_json(line)


def test_passage_to_index_chunk_conversion_shape() -> None:
    passage = Passage(
        passage_id="p-7",
        text="hello",
        title="T",
        source="S",
        question="Q?",
        long_answers=["a"],
    )

    chunk = ingest_multihop._passage_to_index_chunk(passage, ordinal=42)

    assert chunk.chunk_id == ingest_multihop._multihop_point_id("p-7")
    assert chunk.chunk_id != "p-7"
    assert chunk.group_id == "p-7"
    uuid.UUID(chunk.chunk_id)
    assert chunk.text == "hello"
    assert chunk.context_text == "hello"
    assert chunk.source_row_ordinal == 42
    assert chunk.start_candidate_idx == 0
    assert chunk.end_candidate_idx == 0
    assert chunk.passage_types == []
    assert chunk.title == "T"
    assert chunk.source == "S"
    assert chunk.question == "Q?"
    assert chunk.document_url is None
    assert chunk.parent_candidate_idx is None
    assert chunk.chunk_kind == "chunk"
    assert chunk.token_count == 0
    assert chunk.context_token_count == 0
    assert chunk.long_answers == ["a"]
    IndexChunk.model_validate_json(chunk.model_dump_json())


def test_multihop_point_id_is_deterministic_and_unique() -> None:
    first = ingest_multihop._multihop_point_id("musique-2hop__460946_294723-0")
    second = ingest_multihop._multihop_point_id("musique-2hop__460946_294723-0")
    other = ingest_multihop._multihop_point_id("musique-2hop__460946_294723-1")

    assert first == second
    assert first != other
    assert str(uuid.UUID(first)) == first
    assert uuid.UUID(ingest_multihop._multihop_point_id("x")).version == 5


def test_per_benchmark_collection_name_passed_to_indexers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    passage_count = 4
    _patch_loader(
        monkeypatch,
        passages=_make_passages(passage_count, prefix="idx"),
        expected_count=passage_count,
    )
    dense_settings: list[Settings] = []
    sparse_settings: list[Settings] = []

    class SpyDenseIndexer:
        def __init__(self, settings: Settings) -> None:
            dense_settings.append(settings)

        def build_from_jsonl_streaming(
            self,
            jsonl_path: Path,
            *,
            lines_per_batch: int,
            max_index_rows: int | None = None,
            max_passages: int | None = None,
        ) -> DenseBuildResult:
            del lines_per_batch, max_index_rows, max_passages
            vector_count = len(jsonl_path.read_text(encoding="utf-8").splitlines())
            return DenseBuildResult(vector_count=vector_count, vector_size=4)

    class SpySparseQdrantIndexer:
        def __init__(self, settings: Settings) -> None:
            sparse_settings.append(settings)

        def build_from_jsonl(
            self,
            jsonl_path: Path,
            *,
            max_index_rows: int | None = None,
            max_passages: int | None = None,
        ) -> SparseQdrantBuildResult:
            del max_index_rows, max_passages
            document_count = len(jsonl_path.read_text(encoding="utf-8").splitlines())
            return SparseQdrantBuildResult(
                document_count=document_count,
                vocabulary_size=7,
                points_updated=document_count,
            )

    monkeypatch.setattr(ingest_multihop, "DenseIndexer", SpyDenseIndexer)
    monkeypatch.setattr(ingest_multihop, "SparseQdrantIndexer", SpySparseQdrantIndexer)

    ingest_multihop.main(["--dataset", "musique"])

    assert len(dense_settings) == 1
    assert len(sparse_settings) == 1
    assert dense_settings[0].qdrant_collection == "musique_passages_qwen3_embed_4b"
    assert sparse_settings[0].qdrant_collection == "musique_passages_qwen3_embed_4b"
    assert dense_settings[0].qdrant_collection == sparse_settings[0].qdrant_collection
    assert dense_settings[0].qdrant_collection != "nq_passages_qwen3_embed_4b"


def test_dry_run_skips_indexer_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    _patch_loader(monkeypatch, passages=_make_passages(2, prefix="dry"), expected_count=2)
    instantiation_counts: dict[str, int] = {"dense": 0, "sparse": 0}

    class FailDenseIndexer:
        def __init__(self, settings: Settings) -> None:
            del settings
            instantiation_counts["dense"] += 1

    class FailSparseQdrantIndexer:
        def __init__(self, settings: Settings) -> None:
            del settings
            instantiation_counts["sparse"] += 1

    monkeypatch.setattr(ingest_multihop, "DenseIndexer", FailDenseIndexer)
    monkeypatch.setattr(ingest_multihop, "SparseQdrantIndexer", FailSparseQdrantIndexer)

    with caplog.at_level(logging.INFO):
        ingest_multihop.main(["--dataset", "musique", "--dry-run"])

    assert instantiation_counts == {"dense": 0, "sparse": 0}
    assert (tmp_path / "multihop_passages__musique.jsonl").exists()
    reconcile_messages = [
        record.getMessage()
        for record in caplog.records
        if record.__dict__.get("stage") == "reconcile"
    ]
    assert any(
        "actual_passage_count=2 expected=2 ratio=1.0000" in msg
        for msg in reconcile_messages
    )
    manifest_path = tmp_path / "multihop_manifest__musique.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dense_indexed_from"] is None


def test_actual_vs_expected_ratio_logged_correctly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        _run_dry_ingest(monkeypatch, tmp_path, actual_count=600, expected_count=1000)

    reconcile_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "reconcile" and record.levelno == logging.INFO
    ]
    assert any("ratio=0.6000" in record.getMessage() for record in reconcile_records)
    anomaly_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "reconcile" and record.levelno == logging.WARNING
    ]
    assert anomaly_records == []


def test_anomaly_flag_fires_below_half_expected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        _run_dry_ingest(monkeypatch, tmp_path, actual_count=400, expected_count=1000)

    anomaly_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "reconcile" and record.levelno == logging.WARNING
    ]
    assert any(
        "anomaly=true reason=ratio_out_of_band ratio=0.4000" in record.getMessage()
        for record in anomaly_records
    )


def test_anomaly_flag_fires_above_two_times_expected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        _run_dry_ingest(monkeypatch, tmp_path, actual_count=2500, expected_count=1000)

    anomaly_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "reconcile" and record.levelno == logging.WARNING
    ]
    assert any(
        "anomaly=true reason=ratio_out_of_band ratio=2.5000" in record.getMessage()
        for record in anomaly_records
    )


@pytest.mark.parametrize(
    ("actual_count", "expected_count"),
    [
        (500, 1000),
        (2000, 1000),
    ],
)
def test_anomaly_boundary_inclusive_at_half_and_double(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    actual_count: int,
    expected_count: int,
) -> None:
    with caplog.at_level(logging.WARNING):
        _run_dry_ingest(
            monkeypatch,
            tmp_path,
            actual_count=actual_count,
            expected_count=expected_count,
        )

    anomaly_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "reconcile" and record.levelno == logging.WARNING
    ]
    assert anomaly_records == []


def test_unknown_dataset_arg_rejected_by_argparse(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        ingest_multihop.main(["--dataset", "bogus"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err


def test_sparse_artifact_names_are_per_benchmark_for_indexers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    passage_count = 4
    _patch_loader(
        monkeypatch,
        passages=_make_passages(passage_count, prefix="sparse"),
        expected_count=passage_count,
    )
    dense_settings: list[Settings] = []
    sparse_settings: list[Settings] = []

    class SpyDenseIndexer:
        def __init__(self, settings: Settings) -> None:
            dense_settings.append(settings)

        def build_from_jsonl_streaming(
            self,
            jsonl_path: Path,
            *,
            lines_per_batch: int,
            max_index_rows: int | None = None,
            max_passages: int | None = None,
        ) -> DenseBuildResult:
            del lines_per_batch, max_index_rows, max_passages
            vector_count = len(jsonl_path.read_text(encoding="utf-8").splitlines())
            return DenseBuildResult(vector_count=vector_count, vector_size=4)

    class SpySparseQdrantIndexer:
        def __init__(self, settings: Settings) -> None:
            sparse_settings.append(settings)

        def build_from_jsonl(
            self,
            jsonl_path: Path,
            *,
            max_index_rows: int | None = None,
            max_passages: int | None = None,
        ) -> SparseQdrantBuildResult:
            del max_index_rows, max_passages
            document_count = len(jsonl_path.read_text(encoding="utf-8").splitlines())
            return SparseQdrantBuildResult(
                document_count=document_count,
                vocabulary_size=7,
                points_updated=document_count,
            )

    monkeypatch.setattr(ingest_multihop, "DenseIndexer", SpyDenseIndexer)
    monkeypatch.setattr(ingest_multihop, "SparseQdrantIndexer", SpySparseQdrantIndexer)

    ingest_multihop.main(["--dataset", "musique"])

    assert len(dense_settings) == 1
    assert len(sparse_settings) == 1
    for settings in [dense_settings[0], sparse_settings[0]]:
        assert settings.sparse_pass1_file == "sparse_pass1__musique.json"
        assert settings.sparse_manifest_file == "sparse_index_manifest__musique.json"
        assert settings.sparse_pass1_path == tmp_path / "sparse_pass1__musique.json"
        assert (
            settings.sparse_manifest_path
            == tmp_path / "sparse_index_manifest__musique.json"
        )
        assert settings.sparse_pass1_file != "sparse_pass1.json"
        assert settings.sparse_manifest_file != "sparse_index_manifest.json"
