from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

import src.ingestion.musique_loader as musique_loader
from src.ingestion.models import Passage
from src.ingestion.musique_loader import MuSiQueLoader

SYNTHETIC_ROWS: list[dict[str, object]] = [
    {
        "id": "musique-row-alpha",
        "paragraphs": [
            {
                "idx": 0,
                "title": "Ada Lovelace",
                "paragraph_text": "Ada was a mathematician.",
                "is_supporting": True,
            },
            {
                "idx": 1,
                "title": "Analytical Engine",
                "paragraph_text": "The Analytical Engine was a mechanical computer design.",
                "is_supporting": False,
            },
        ],
    },
    {
        "id": "musique-row-beta",
        "paragraphs": [
            {
                "idx": 0,
                "title": "Mercury",
                "paragraph_text": "Mercury is the closest planet to the Sun.",
                "is_supporting": True,
            },
        ],
    },
]


def _patch_rows(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]]) -> None:
    def fake_iter_rows() -> Iterator[Mapping[str, object]]:
        return iter(rows)

    monkeypatch.setattr(musique_loader, "_iter_rows_from_hf", fake_iter_rows)


def _non_empty_paragraph_count(rows: list[dict[str, object]]) -> int:
    count = 0
    for row in rows:
        paragraphs = row["paragraphs"]
        assert isinstance(paragraphs, list)
        for paragraph in paragraphs:
            assert isinstance(paragraph, dict)
            text = paragraph["paragraph_text"]
            assert isinstance(text, str)
            if text.strip():
                count += 1
    return count


def test_musique_loader_satisfies_multihop_protocol() -> None:
    loader = MuSiQueLoader()

    assert isinstance(loader.dataset_name, str)
    assert isinstance(loader.expected_collection_name, str)
    assert isinstance(loader.expected_passage_count, int)
    assert callable(loader.iter_passages)


def test_musique_loader_dataset_name_collection_count() -> None:
    loader = MuSiQueLoader()

    assert loader.dataset_name == "musique"
    assert loader.expected_collection_name == "musique_passages_qwen3_embed_4b"
    assert loader.expected_passage_count == 100_000


def test_iter_passages_yields_one_passage_per_paragraph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    passages = list(MuSiQueLoader().iter_passages())

    assert len(passages) == _non_empty_paragraph_count(SYNTHETIC_ROWS)


def test_iter_passages_passage_ids_are_stable_and_unique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)
    loader = MuSiQueLoader()

    first_run = [passage.passage_id for passage in loader.iter_passages()]
    second_run = [passage.passage_id for passage in loader.iter_passages()]

    assert first_run == second_run
    assert len(set(first_run)) == len(first_run)
    assert first_run[0] == "musique-musique-row-alpha-0"


def test_iter_passages_title_and_text_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    first_passage = next(MuSiQueLoader().iter_passages())

    assert first_passage.title == "Ada Lovelace"
    assert first_passage.source == "Ada Lovelace"
    assert first_passage.text == "Ada was a mathematician."


def test_iter_passages_skips_empty_paragraphs(monkeypatch: pytest.MonkeyPatch) -> None:
    rows: list[dict[str, object]] = [
        {
            "id": "gamma",
            "paragraphs": [
                {
                    "idx": 2,
                    "title": "Empty",
                    "paragraph_text": "   ",
                    "is_supporting": False,
                },
                {
                    "idx": 5,
                    "title": "Real",
                    "paragraph_text": "Content.",
                    "is_supporting": True,
                },
                {
                    "idx": 9,
                    "title": "Also Real",
                    "paragraph_text": "More content.",
                    "is_supporting": True,
                },
            ],
        },
    ]
    _patch_rows(monkeypatch, rows)

    passages = list(MuSiQueLoader().iter_passages())

    assert [passage.passage_id for passage in passages] == [
        "musique-gamma-5",
        "musique-gamma-9",
    ]
    assert [passage.text for passage in passages] == ["Content.", "More content."]


def test_iter_passages_returns_passage_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_rows(monkeypatch, SYNTHETIC_ROWS)

    passages = list(MuSiQueLoader().iter_passages())

    assert all(isinstance(passage, Passage) for passage in passages)
