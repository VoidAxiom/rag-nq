from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

import src.ingestion.twowikimhqa_loader as twowikimhqa_loader
from src.ingestion.models import Passage
from src.ingestion.twowikimhqa_loader import TwoWikiMhqaLoader

SYNTHETIC_ROWS: list[dict[str, object]] = [
    {
        "_id": "bridge-alpha",
        "context": [
            [
                "Ada Lovelace",
                ["Ada was a mathematician.", "She wrote notes about computing."],
            ],
            [
                "Analytical Engine",
                [
                    "The Analytical Engine was proposed by Charles Babbage.",
                    "It was a mechanical general-purpose computer design.",
                ],
            ],
        ],
    },
    {
        "_id": "single-beta",
        "context": [
            [
                "Mercury",
                ["Mercury is the closest planet to the Sun.", "It has a short year."],
            ],
        ],
    },
]


def _patch_rows(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]]) -> None:
    def fake_iter_rows() -> Iterator[Mapping[str, object]]:
        return iter(rows)

    monkeypatch.setattr(twowikimhqa_loader, "_iter_rows_from_hf", fake_iter_rows)


def _non_empty_paragraph_count(rows: list[dict[str, object]]) -> int:
    count = 0
    for row in rows:
        context = row["context"]
        assert isinstance(context, list)
        for paragraph in context:
            assert isinstance(paragraph, list)
            assert len(paragraph) == 2
            sentences = paragraph[1]
            assert isinstance(sentences, list)
            sentence_values: list[str] = []
            for sentence in sentences:
                assert isinstance(sentence, str)
                sentence_values.append(sentence)
            text = " ".join(sentence_values).strip()
            if text:
                count += 1
    return count


def test_twowikimhqa_loader_satisfies_multihop_protocol() -> None:
    loader = TwoWikiMhqaLoader()

    assert isinstance(loader.dataset_name, str)
    assert isinstance(loader.expected_collection_name, str)
    assert isinstance(loader.expected_passage_count, int)
    assert callable(loader.iter_passages)


def test_twowikimhqa_loader_dataset_name_collection_count() -> None:
    loader = TwoWikiMhqaLoader()

    assert loader.dataset_name == "2wikimhqa"
    assert loader.expected_collection_name == "2wikimhqa_passages_qwen3_embed_4b"
    assert loader.expected_passage_count == 430_000


def test_iter_passages_yields_one_passage_per_paragraph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    passages = list(TwoWikiMhqaLoader().iter_passages())

    assert len(passages) == _non_empty_paragraph_count(SYNTHETIC_ROWS)


def test_iter_passages_passage_ids_are_stable_and_unique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)
    loader = TwoWikiMhqaLoader()

    first_run = [passage.passage_id for passage in loader.iter_passages()]
    second_run = [passage.passage_id for passage in loader.iter_passages()]

    assert first_run == second_run
    assert len(set(first_run)) == len(first_run)
    assert first_run[0] == "2wikimhqa-bridge-alpha-0"


def test_iter_passages_title_and_text_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    first_passage = next(TwoWikiMhqaLoader().iter_passages())

    assert first_passage.title == "Ada Lovelace"
    assert first_passage.source == "Ada Lovelace"
    assert first_passage.text == "Ada was a mathematician. She wrote notes about computing."


def test_iter_passages_skips_empty_paragraphs(monkeypatch: pytest.MonkeyPatch) -> None:
    rows: list[dict[str, object]] = [
        {
            "_id": "gamma",
            "context": [
                ["Empty", []],
                ["Real", ["Content."]],
                ["Also Real", ["More content."]],
            ],
        },
    ]
    _patch_rows(monkeypatch, rows)

    passages = list(TwoWikiMhqaLoader().iter_passages())

    assert [passage.passage_id for passage in passages] == [
        "2wikimhqa-gamma-1",
        "2wikimhqa-gamma-2",
    ]
    assert [passage.text for passage in passages] == ["Content.", "More content."]


def test_iter_passages_returns_passage_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    passages = list(TwoWikiMhqaLoader().iter_passages())

    assert all(isinstance(passage, Passage) for passage in passages)
