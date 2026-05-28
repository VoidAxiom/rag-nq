from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

import src.ingestion.hotpotqa_loader as hotpotqa_loader
from src.ingestion.hotpotqa_loader import HotpotqaLoader
from src.ingestion.models import Passage

SYNTHETIC_ROWS: list[dict[str, object]] = [
    {
        "id": "alpha",
        "context": {
            "title": ["Bob the Builder", "Cat Hat"],
            "sentences": [
                ["Bob is yellow.", "Bob builds things."],
                ["The cat has a hat.", "The hat is striped."],
            ],
        },
    },
    {
        "id": "beta",
        "context": {
            "title": ["Solo"],
            "sentences": [
                ["A lone paragraph.", "With two sentences."],
            ],
        },
    },
]


def _patch_rows(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]]) -> None:
    def fake_iter_rows() -> Iterator[Mapping[str, object]]:
        return iter(rows)

    monkeypatch.setattr(hotpotqa_loader, "_iter_rows_from_hf", fake_iter_rows)


def _non_empty_paragraph_count(rows: list[dict[str, object]]) -> int:
    count = 0
    for row in rows:
        context = row["context"]
        assert isinstance(context, dict)
        sentence_lists = context["sentences"]
        assert isinstance(sentence_lists, list)
        for sentences in sentence_lists:
            assert isinstance(sentences, list)
            text = " ".join(sentences).strip()
            if text:
                count += 1
    return count


def test_hotpotqa_loader_satisfies_multihop_protocol() -> None:
    loader = HotpotqaLoader()

    assert isinstance(loader.dataset_name, str)
    assert isinstance(loader.expected_collection_name, str)
    assert isinstance(loader.expected_passage_count, int)
    assert callable(loader.iter_passages)


def test_hotpotqa_loader_dataset_name_collection_count() -> None:
    loader = HotpotqaLoader()

    assert loader.dataset_name == "hotpotqa"
    assert loader.expected_collection_name == "hotpotqa_passages_qwen3_embed_4b"
    assert loader.expected_passage_count == 500_000


def test_iter_passages_yields_one_passage_per_paragraph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    passages = list(HotpotqaLoader().iter_passages())

    assert len(passages) == _non_empty_paragraph_count(SYNTHETIC_ROWS)


def test_iter_passages_passage_ids_are_stable_and_unique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)
    loader = HotpotqaLoader()

    first_run = [passage.passage_id for passage in loader.iter_passages()]
    second_run = [passage.passage_id for passage in loader.iter_passages()]

    assert first_run == second_run
    assert len(set(first_run)) == len(first_run)
    assert first_run[0] == "hotpotqa-alpha-0"


def test_iter_passages_title_and_text_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    first_passage = next(HotpotqaLoader().iter_passages())

    assert first_passage.title == "Bob the Builder"
    assert first_passage.source == "Bob the Builder"
    assert first_passage.text == "Bob is yellow. Bob builds things."


def test_iter_passages_skips_empty_paragraphs(monkeypatch: pytest.MonkeyPatch) -> None:
    rows: list[dict[str, object]] = [
        {
            "id": "gamma",
            "context": {
                "title": ["Empty", "Real", "Also Real"],
                "sentences": [
                    [],
                    ["Content."],
                    ["More content."],
                ],
            },
        },
    ]
    _patch_rows(monkeypatch, rows)

    passages = list(HotpotqaLoader().iter_passages())

    assert [passage.passage_id for passage in passages] == [
        "hotpotqa-gamma-1",
        "hotpotqa-gamma-2",
    ]
    assert [passage.text for passage in passages] == ["Content.", "More content."]


def test_iter_passages_returns_passage_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    passages = list(HotpotqaLoader().iter_passages())

    assert all(isinstance(passage, Passage) for passage in passages)
