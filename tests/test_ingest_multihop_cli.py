from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

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


def _make_row_passages(
    *, rows: int, paragraphs_per_row: int, prefix: str = "musique"
) -> list[Passage]:
    passages: list[Passage] = []
    for row_idx in range(rows):
        for para_idx in range(paragraphs_per_row):
            passages.append(
                Passage(
                    passage_id=f"{prefix}-row{row_idx}-{para_idx}",
                    text=f"text {row_idx}/{para_idx}",
                    title=f"title {row_idx}/{para_idx}",
                    source=f"source {row_idx}/{para_idx}",
                    question=f"q {row_idx}?",
                    long_answers=[f"a {row_idx}/{para_idx}"],
                )
            )
    return passages


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
    ingest_multihop.main(["--dataset", "musique", "--dry-run", "--force"])


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

    ingest_multihop.main(["--dataset", dataset_arg, "--dry-run", "--force"])

    assert calls == [expected_benchmark]


def test_jsonl_written_at_per_benchmark_path_with_index_chunk_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    passages = _make_passages(3, prefix="synthetic")
    _patch_loader(monkeypatch, passages=passages, expected_count=3)

    ingest_multihop.main(["--dataset", "musique", "--dry-run", "--force"])

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


def test_sample_size_caps_hf_row_iterator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    passages = _make_row_passages(rows=10, paragraphs_per_row=3)
    _patch_loader(monkeypatch, passages=passages, expected_count=len(passages))

    ingest_multihop.main(
        ["--dataset", "musique", "--sample-size", "4", "--dry-run", "--force"]
    )

    jsonl_path = tmp_path / "multihop_passages__musique.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 12
    objects = [json.loads(line) for line in lines]
    assert [obj["group_id"] for obj in objects] == [
        "musique-row0-0",
        "musique-row0-1",
        "musique-row0-2",
        "musique-row1-0",
        "musique-row1-1",
        "musique-row1-2",
        "musique-row2-0",
        "musique-row2-1",
        "musique-row2-2",
        "musique-row3-0",
        "musique-row3-1",
        "musique-row3-2",
    ]


def test_cap_passages_yields_prefix_of_emitted_row_keys() -> None:
    passage_ids = ("r-0-0", "r-0-1", "r-2-0", "r-2-1", "r-5-0", "r-9-0")
    passages = [
        Passage(
            passage_id=passage_id,
            text=f"text {passage_id}",
            title=f"title {passage_id}",
            source="unit",
            question="q?",
            long_answers=["a"],
        )
        for passage_id in passage_ids
    ]

    capped = list(ingest_multihop._cap_passages_by_row(iter(passages), max_rows=2))
    capped_row_keys = [passage.passage_id.rsplit("-", 1)[0] for passage in capped]

    assert capped_row_keys == ["r-0", "r-0", "r-2", "r-2"]
    assert set(capped_row_keys) == {"r-0", "r-2"}
    assert [passage.passage_id for passage in capped] == [
        "r-0-0",
        "r-0-1",
        "r-2-0",
        "r-2-1",
    ]


def test_cap_passages_rejects_malformed_passage_id() -> None:
    passage = Passage(
        passage_id="bare",
        text="text",
        title="title",
        source="unit",
        question="q?",
        long_answers=["a"],
    )

    with pytest.raises(ValueError, match=r"passage_id=.*_cap_passages_by_row"):
        list(ingest_multihop._cap_passages_by_row(iter([passage]), max_rows=1))


def test_cap_passages_consumes_one_extra_probe_only() -> None:
    passages = _make_row_passages(rows=4, paragraphs_per_row=3)
    next_count = 0

    def counted_passages() -> Iterator[Passage]:
        nonlocal next_count
        for passage in passages:
            next_count += 1
            yield passage

    capped = list(ingest_multihop._cap_passages_by_row(counted_passages(), max_rows=2))

    assert [passage.passage_id for passage in capped] == [
        "musique-row0-0",
        "musique-row0-1",
        "musique-row0-2",
        "musique-row1-0",
        "musique-row1-1",
        "musique-row1-2",
    ]
    accepted_prefix_count = 2 * 3
    assert len(capped) == accepted_prefix_count
    # 2 accepted rows * 3 passages each, plus one row2 probe to discover the cap.
    assert next_count == accepted_prefix_count + 1


def test_sample_size_suppresses_anomaly_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    passages = _make_row_passages(rows=5000, paragraphs_per_row=1)
    _patch_loader(monkeypatch, passages=passages, expected_count=100_000)

    with caplog.at_level(logging.INFO):
        ingest_multihop.main(
            ["--dataset", "musique", "--sample-size", "5000", "--dry-run", "--force"]
        )

    warning_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "reconcile" and record.levelno == logging.WARNING
    ]
    assert warning_records == []
    sampled_reconcile_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "reconcile"
        and record.levelno == logging.INFO
    ]
    assert len(sampled_reconcile_records) == 1
    assert (
        "mode=sampled actual_passage_count=5000 sample_size=5000"
        in sampled_reconcile_records[0].getMessage()
    )


def test_full_corpus_preserves_anomaly_check(
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


def test_sample_size_emits_sample_log_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    passages = _make_row_passages(rows=5000, paragraphs_per_row=1)
    _patch_loader(monkeypatch, passages=passages, expected_count=100_000)

    with caplog.at_level(logging.INFO):
        ingest_multihop.main(
            ["--dataset", "musique", "--sample-size", "5000", "--dry-run", "--force"]
        )

    sample_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "sample" and record.levelno == logging.INFO
    ]
    assert len(sample_records) == 1
    assert "sample_size=5000" in sample_records[0].getMessage()


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

    ingest_multihop.main(["--dataset", "musique", "--force"])

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
        ingest_multihop.main(["--dataset", "musique", "--dry-run", "--force"])

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


def test_positive_int_validator_rejects_non_positive() -> None:
    for rejected_sample_size in ("0", "-5"):
        with pytest.raises(SystemExit) as exc_info:
            ingest_multihop._parse_args(
                ["--dataset", "musique", "--sample-size", rejected_sample_size]
            )

        assert exc_info.value.code == 2

    args = ingest_multihop._parse_args(["--dataset", "musique", "--sample-size", "1"])

    assert args.sample_size == 1


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

    ingest_multihop.main(["--dataset", "musique", "--force"])

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


def test_memory_guard_aborts_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "psutil.virtual_memory",
        lambda: SimpleNamespace(available=5 * 1024**3),
    )

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exc_info:
        ingest_multihop.main(["--dataset", "musique"])

    error_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "memory_guard" and record.levelno == logging.ERROR
    ]
    messages = [str(exc_info.value), *(record.getMessage() for record in error_records)]
    assert any("memory_guard abort" in message and "5.00" in message for message in messages)


def test_force_bypasses_memory_guard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "psutil.virtual_memory",
        lambda: SimpleNamespace(available=5 * 1024**3),
    )
    _patch_loader(
        monkeypatch,
        passages=_make_passages(2, prefix="force"),
        expected_count=2,
    )

    with caplog.at_level(logging.INFO):
        ingest_multihop.main(["--dataset", "musique", "--force", "--dry-run"])

    guard_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "memory_guard" and record.levelno == logging.INFO
    ]
    assert any(
        "bypassed" in record.getMessage() and "--force" in record.getMessage()
        for record in guard_records
    )


def test_force_without_dry_run_bypasses_memory_guard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "psutil.virtual_memory",
        lambda: SimpleNamespace(available=5 * 1024**3),
    )

    # Stub indexers so the (non-dry-run) path completes without real I/O.
    class StubDense:
        def __init__(self, settings: Settings) -> None:
            del settings

        def build_from_jsonl_streaming(
            self,
            jsonl_path: Path,
            *,
            lines_per_batch: int,
            max_index_rows: int | None = None,
            max_passages: int | None = None,
        ) -> DenseBuildResult:
            del jsonl_path, lines_per_batch, max_index_rows, max_passages
            return DenseBuildResult(vector_count=0, vector_size=0)

    class StubSparse:
        def __init__(self, settings: Settings) -> None:
            del settings

        def build_from_jsonl(
            self,
            jsonl_path: Path,
            *,
            max_index_rows: int | None = None,
            max_passages: int | None = None,
        ) -> SparseQdrantBuildResult:
            del jsonl_path, max_index_rows, max_passages
            return SparseQdrantBuildResult(
                document_count=0, vocabulary_size=0, points_updated=0
            )

    monkeypatch.setattr(ingest_multihop, "DenseIndexer", StubDense)
    monkeypatch.setattr(ingest_multihop, "SparseQdrantIndexer", StubSparse)
    _patch_loader(
        monkeypatch,
        passages=_make_passages(2, prefix="force-real"),
        expected_count=2,
    )

    with caplog.at_level(logging.INFO):
        ingest_multihop.main(["--dataset", "musique", "--force"])

    guard_records = [
        record
        for record in caplog.records
        if record.__dict__.get("stage") == "memory_guard" and record.levelno == logging.INFO
    ]
    assert any(
        "bypassed" in record.getMessage() and "--force" in record.getMessage()
        for record in guard_records
    )
