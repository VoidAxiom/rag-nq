from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

import src.ingestion.musique_loader as musique_loader
from src.ingestion.models import Passage
from src.ingestion.musique_loader import MuSiQueGoldQuestion, MuSiQueLoader

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


def _gold_question_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "musique-row-alpha",
            "question": "Who designed the Analytical Engine?",
            "answer": "Ada Lovelace",
            "answer_aliases": ["Augusta Ada King"],
            "paragraphs": [
                {
                    "idx": 0,
                    "is_supporting": True,
                    "paragraph_text": "Paragraph about Ada Lovelace.",
                },
                {
                    "idx": 1,
                    "is_supporting": True,
                    "paragraph_text": "Paragraph about the Analytical Engine.",
                },
                {
                    "idx": 2,
                    "is_supporting": False,
                    "paragraph_text": "Paragraph about Charles Babbage.",
                },
            ],
        },
        {
            "id": "musique-row-beta",
            "question": "What is the closest planet to the Sun?",
            "answer": "Mercury",
            "answer_aliases": [],
            "paragraphs": [
                {
                    "idx": 0,
                    "is_supporting": True,
                    "paragraph_text": "Paragraph about Mercury.",
                },
            ],
        },
        {
            "id": "skip-empty",
            "question": "",
            "answer": "Skip me",
            "answer_aliases": [],
            "paragraphs": [
                {
                    "idx": 0,
                    "is_supporting": True,
                    "paragraph_text": "Paragraph about skipped content.",
                },
            ],
        },
        {
            "id": "skip-no-answer",
            "question": "Q?",
            "answer": "   ",
            "answer_aliases": [],
            "paragraphs": [
                {
                    "idx": 0,
                    "is_supporting": True,
                    "paragraph_text": "Paragraph about unanswered content.",
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


def test_iter_gold_questions_skips_rows_with_empty_question_or_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, _gold_question_rows())

    gold_questions = list(MuSiQueLoader().iter_gold_questions())

    assert len(gold_questions) == 2
    assert all(isinstance(gold, MuSiQueGoldQuestion) for gold in gold_questions)


def test_iter_gold_questions_supporting_ids_use_canonical_id_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, _gold_question_rows())

    gold_by_row = {
        gold.row_id: gold for gold in MuSiQueLoader().iter_gold_questions()
    }

    assert gold_by_row["musique-row-alpha"].supporting_passage_ids == (
        "musique-musique-row-alpha-0",
        "musique-musique-row-alpha-1",
    )
    assert gold_by_row["musique-row-beta"].supporting_passage_ids == (
        "musique-musique-row-beta-0",
    )


def test_iter_gold_questions_skips_supporting_paragraphs_with_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, object]] = [
        {
            "id": "row-empty-supporting-text",
            "question": "Which paragraph is usable?",
            "answer": "Usable paragraph",
            "answer_aliases": [],
            "paragraphs": [
                {
                    "idx": 0,
                    "is_supporting": True,
                    "paragraph_text": "Paragraph about usable evidence.",
                },
                {
                    "idx": 1,
                    "is_supporting": True,
                    "paragraph_text": "   ",
                },
            ],
        },
    ]
    _patch_rows(monkeypatch, rows)

    gold_question = next(MuSiQueLoader().iter_gold_questions())

    assert gold_question.supporting_passage_ids == (
        "musique-row-empty-supporting-text-0",
    )


def test_iter_gold_questions_skips_row_with_no_supporting_paragraphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, object]] = [
        {
            "id": "row-no-support",
            "question": "Which paragraphs support the answer?",
            "answer": "None",
            "answer_aliases": [],
            "paragraphs": [
                {
                    "idx": 0,
                    "is_supporting": False,
                    "paragraph_text": "Paragraph about unrelated evidence.",
                },
                {
                    "idx": 1,
                    "is_supporting": False,
                    "paragraph_text": "Paragraph about another topic.",
                },
            ],
        },
    ]
    _patch_rows(monkeypatch, rows)

    assert list(MuSiQueLoader().iter_gold_questions()) == []


def test_iter_gold_questions_skips_row_when_all_supporting_paragraphs_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, object]] = [
        {
            "id": "row-empty-supports",
            "question": "Which empty paragraphs support the answer?",
            "answer": "None",
            "answer_aliases": [],
            "paragraphs": [
                {
                    "idx": 0,
                    "is_supporting": True,
                    "paragraph_text": "",
                },
                {
                    "idx": 1,
                    "is_supporting": True,
                    "paragraph_text": "   ",
                },
            ],
        },
    ]
    _patch_rows(monkeypatch, rows)

    assert list(MuSiQueLoader().iter_gold_questions()) == []


def test_iter_gold_questions_gold_answers_merge_alias_and_dedupe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _gold_question_rows()
    rows.append(
        {
            "id": "duplicate-alias",
            "question": "Duplicate alias?",
            "answer": "X",
            "answer_aliases": ["X", "Y"],
            "paragraphs": [
                {
                    "idx": 0,
                    "is_supporting": True,
                    "paragraph_text": "Some text.",
                },
            ],
        }
    )
    _patch_rows(monkeypatch, rows)

    gold_by_row = {
        gold.row_id: gold for gold in MuSiQueLoader().iter_gold_questions()
    }

    assert gold_by_row["musique-row-alpha"].gold_answers == (
        "Ada Lovelace",
        "Augusta Ada King",
    )
    assert gold_by_row["duplicate-alias"].gold_answers == ("X", "Y")


def test_iter_gold_questions_supporting_ids_sorted_lexicographically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, object]] = [
        {
            "id": "row-zeta",
            "question": "Zeta?",
            "answer": "Zeta",
            "answer_aliases": [],
            "paragraphs": [
                {
                    "idx": 2,
                    "is_supporting": True,
                    "paragraph_text": "Paragraph about zeta two.",
                },
                {
                    "idx": 10,
                    "is_supporting": True,
                    "paragraph_text": "Paragraph about zeta ten.",
                },
            ],
        },
    ]
    _patch_rows(monkeypatch, rows)

    gold_question = next(MuSiQueLoader().iter_gold_questions())

    assert gold_question.supporting_passage_ids == (
        "musique-row-zeta-10",
        "musique-row-zeta-2",
    )


def test_iter_gold_questions_is_deterministic_across_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, _gold_question_rows())
    loader = MuSiQueLoader()

    first_run = list(loader.iter_gold_questions())
    second_run = list(loader.iter_gold_questions())

    assert first_run == second_run
