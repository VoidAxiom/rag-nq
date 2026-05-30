from __future__ import annotations

import sys
import types
from collections.abc import Sequence

import pytest
import torch

from src.models.query_schemas import PassageHit
from src.retrieval import rerank
from src.retrieval.rerank import (
    build_default_cross_encoder,
    build_rerank_input,
    dedupe_hits,
    rerank_hits,
)


class FakeCrossEncoder:
    def predict(self, pairs):
        return [10.0 if "better" in passage else 1.0 for _query, passage in pairs]


class FakeCrossEncoderWithProgressFlag:
    def __init__(self) -> None:
        self.show_progress_bar: bool | None = None

    def predict(self, pairs, *, show_progress_bar: bool):
        self.show_progress_bar = show_progress_bar
        return [10.0 if "better" in passage else 1.0 for _query, passage in pairs]


class RecordingCrossEncoder:
    def __init__(self, model_name: str, *args: object, **kwargs: object) -> None:
        self.model_name = model_name
        self.args = args
        self.kwargs = kwargs

    def predict(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [0.0 for _pair in pairs]


def test_build_rerank_input_prefers_bounded_context_text() -> None:
    hit = PassageHit(
        point_id="p1",
        title="Doc",
        text="short text",
        context_text="one two three four",
    )

    assert build_rerank_input(hit, context_token_budget=3) == "Title: Doc\none two three"


def test_build_default_cross_encoder_uses_mps_fp16_on_apple_silicon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rerank, "_is_apple_silicon", lambda: True)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(CrossEncoder=RecordingCrossEncoder),
    )

    model = build_default_cross_encoder("cross-encoder/test")

    assert isinstance(model, RecordingCrossEncoder)
    assert model.model_name == "cross-encoder/test"
    assert model.args == ()
    assert model.kwargs == {
        "device": "mps",
        "model_kwargs": {"torch_dtype": torch.float16},
    }


def test_build_default_cross_encoder_falls_back_to_bare_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rerank, "_is_apple_silicon", lambda: False)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(CrossEncoder=RecordingCrossEncoder),
    )

    model = build_default_cross_encoder("cross-encoder/test")

    assert isinstance(model, RecordingCrossEncoder)
    assert model.model_name == "cross-encoder/test"
    assert model.args == ()
    assert model.kwargs == {}


def test_is_apple_silicon_returns_false_when_torch_unimportable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)

    assert rerank._is_apple_silicon() is False


def test_is_apple_silicon_returns_false_when_mps_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_torch = types.SimpleNamespace(backends=types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert rerank._is_apple_silicon() is False


def test_is_apple_silicon_returns_false_when_mps_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_torch = types.SimpleNamespace(
        backends=types.SimpleNamespace(
            mps=types.SimpleNamespace(is_available=lambda: False)
        )
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert rerank._is_apple_silicon() is False


def test_rerank_hits_orders_by_cross_encoder_score() -> None:
    hits = [
        PassageHit(point_id="p1", text="plain", fusion_rank=1),
        PassageHit(point_id="p2", text="better evidence", fusion_rank=2),
    ]

    reranked = rerank_hits(
        query="q",
        hits=hits,
        model=FakeCrossEncoder(),
        context_token_budget=100,
    )

    assert [hit.point_id for hit in reranked] == ["p2", "p1"]
    assert [hit.rerank_rank for hit in reranked] == [1, 2]
    assert reranked[0].rerank_score == pytest.approx(10.0)
    assert hits[0].rerank_rank is None


def test_rerank_hits_disables_cross_encoder_progress_bar() -> None:
    hits = [
        PassageHit(point_id="p1", text="plain", fusion_rank=1),
        PassageHit(point_id="p2", text="better evidence", fusion_rank=2),
    ]
    model = FakeCrossEncoderWithProgressFlag()

    reranked = rerank_hits(
        query="q",
        hits=hits,
        model=model,
        context_token_budget=100,
    )

    assert [hit.point_id for hit in reranked] == ["p2", "p1"]
    assert model.show_progress_bar is False


def test_dedupe_hits_uses_title_and_context_text_with_aliases_and_metrics() -> None:
    hits = [
        PassageHit(
            point_id="p1",
            title="Doc",
            text="short",
            context_text="Same Evidence",
            dense_rank=2,
            sparse_rank=1,
            fusion_rank=1,
        ),
        PassageHit(
            point_id="p2",
            title="Doc",
            text="different text",
            context_text=" same   evidence ",
            dense_rank=1,
            sparse_rank=2,
            fusion_rank=2,
        ),
        PassageHit(
            point_id="p3",
            title="Other Doc",
            text="short",
            context_text="Same Evidence",
            fusion_rank=3,
        ),
    ]

    result = dedupe_hits(hits, top_k=10)

    assert [hit.point_id for hit in result.hits] == ["p1", "p3"]
    assert [hit.dedupe_rank for hit in result.hits] == [1, 2]
    assert result.hits[0].duplicate_aliases[0].point_id == "p2"
    assert result.hits[0].duplicate_aliases[0].dense_rank == 1
    assert result.hits[0].duplicate_aliases[0].sparse_rank == 2
    assert result.hits[0].duplicate_aliases[0].fusion_rank == 2
    assert result.metrics.raw_count == 3
    assert result.metrics.unique_count == 2
    assert result.metrics.dedupe_drop_count == 1
    assert result.metrics.dedupe_drop_rate == pytest.approx(1 / 3)


def test_dedupe_hits_falls_back_to_text_when_context_text_empty() -> None:
    hits = [
        PassageHit(point_id="p1", title="Doc", text="Same Evidence", context_text=None),
        PassageHit(point_id="p2", title="Doc", text=" same   evidence ", context_text=""),
    ]

    result = dedupe_hits(hits, top_k=10)

    assert [hit.point_id for hit in result.hits] == ["p1"]
    assert result.hits[0].duplicate_aliases[0].point_id == "p2"


def test_dedupe_hits_prefers_context_text_over_matching_text() -> None:
    hits = [
        PassageHit(point_id="p1", title="Doc", text="Same text", context_text="Context one"),
        PassageHit(point_id="p2", title="Doc", text="Same text", context_text="Context two"),
    ]

    result = dedupe_hits(hits, top_k=10)

    assert [hit.point_id for hit in result.hits] == ["p1", "p2"]
    assert result.metrics.dedupe_drop_count == 0
