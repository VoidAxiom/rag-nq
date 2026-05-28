from __future__ import annotations

import json
import os
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

JSON_ENCODED_ROWS: list[dict[str, object]] = [
    {
        "_id": "json-alpha",
        "context": [
            ['"Tokyo"', '["s1", "s2"]'],
            ['"Kyoto"', '["old capital", "temples"]'],
        ],
    },
    {
        "_id": "json-beta",
        "context": [
            ['"Osaka"', '["port", "food"]'],
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
            raw_sentences = paragraph[1]
            if isinstance(raw_sentences, str):
                sentences: object = json.loads(raw_sentences)
            else:
                sentences = raw_sentences
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


def test_iter_passages_decodes_json_encoded_title_and_sentences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_rows(monkeypatch, JSON_ENCODED_ROWS)

    passages = list(TwoWikiMhqaLoader().iter_passages())

    assert len(passages) == _non_empty_paragraph_count(JSON_ENCODED_ROWS)
    assert passages[0].title == "Tokyo"
    assert passages[0].text == "s1 s2"
    assert passages[0].source == passages[0].title
    assert [passage.passage_id for passage in passages] == [
        "2wikimhqa-json-alpha-0",
        "2wikimhqa-json-alpha-1",
        "2wikimhqa-json-beta-0",
    ]


def test_iter_passages_raises_on_malformed_sentences_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, object]] = [
        {
            "_id": "bad-json",
            "context": [
                ['"Tokyo"', "not json"],
            ],
        },
    ]
    _patch_rows(monkeypatch, rows)

    with pytest.raises(TypeError, match="is not valid JSON"):
        list(TwoWikiMhqaLoader().iter_passages())


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


@pytest.mark.live_network
def test_iter_passages_live_hf_first_row_smoke() -> None:
    if os.getenv("RAG_RUN_LIVE_NETWORK_TESTS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        pytest.skip("Set RAG_RUN_LIVE_NETWORK_TESTS=1 to run live-network HF tests.")

    pytest.importorskip("datasets")
    try:
        from datasets.exceptions import DatasetNotFoundError
    except ImportError:
        DatasetNotFoundError: type[BaseException] = OSError

    loader = TwoWikiMhqaLoader()
    assert loader.dataset_name == "2wikimhqa"

    try:
        first_passage = next(loader.iter_passages())
    except (OSError, ConnectionError, DatasetNotFoundError) as exc:
        pytest.skip(f"live HF unavailable: {exc}")

    assert isinstance(first_passage, Passage)
    assert first_passage.text
    assert isinstance(first_passage.title, str)
    assert not first_passage.title.startswith('"')
