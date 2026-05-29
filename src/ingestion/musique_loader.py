"""MuSiQue multihop benchmark loader."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from src.ingestion.models import Passage

_HF_DATASET_NAME = "bdsaglam/musique"
_HF_DATASET_CONFIG = "answerable"
_HF_DATASET_SPLIT = "validation"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MuSiQueGoldQuestion:
    row_id: str
    question: str
    gold_answers: tuple[str, ...]
    supporting_passage_ids: tuple[str, ...]


class MuSiQueLoader:
    """Loader for MuSiQue-Ans validation passages."""

    _DATASET_NAME = "musique"
    _COLLECTION_NAME = "musique_passages_qwen3_embed_4b"
    _PASSAGE_COUNT = 100_000

    @property
    def dataset_name(self) -> str:
        """Return the canonical benchmark dataset name."""

        return self._DATASET_NAME

    @property
    def expected_collection_name(self) -> str:
        """Return the expected Qdrant collection name."""

        return self._COLLECTION_NAME

    @property
    def expected_passage_count(self) -> int:
        """Return the approximate passage-count sentinel for downstream sanity checks."""

        return self._PASSAGE_COUNT

    def iter_passages(self) -> Iterator[Passage]:
        """Iterate one normalized passage per MuSiQue paragraph."""

        for row in _iter_rows_from_hf():
            row_id = str(row["id"])
            paragraphs = _require_sequence(row["paragraphs"], "paragraphs")
            for list_idx, raw_paragraph in enumerate(paragraphs):
                paragraph = _require_mapping(raw_paragraph, f"paragraphs[{list_idx}]")
                para_idx_value = paragraph.get("idx")
                if not isinstance(para_idx_value, int):
                    raise TypeError(f"MuSiQue paragraphs[{list_idx}].idx must be an int.")
                title_value_raw = paragraph.get("title")
                if not isinstance(title_value_raw, str):
                    raise TypeError(f"MuSiQue paragraphs[{list_idx}].title must be a string.")
                text_value = paragraph.get("paragraph_text")
                if not isinstance(text_value, str):
                    raise TypeError(
                        f"MuSiQue paragraphs[{list_idx}].paragraph_text must be a string."
                    )
                text = text_value.strip()
                if not text:
                    continue
                title = title_value_raw or None
                yield Passage(
                    passage_id=f"musique-{row_id}-{para_idx_value}",
                    text=text,
                    source=title,
                    title=title,
                )

    def iter_gold_questions(self) -> Iterator[MuSiQueGoldQuestion]:
        """Iterate MuSiQue gold questions and supporting passage ids."""

        for row in _iter_rows_from_hf():
            row_id = str(row["id"])
            question_raw = row.get("question")
            if not isinstance(question_raw, str):
                raise TypeError("MuSiQue question must be a string.")
            question = question_raw.strip()
            if not question:
                LOGGER.debug("Skipping MuSiQue row %s with empty question.", row_id)
                continue

            answer_raw = row.get("answer")
            if not isinstance(answer_raw, str):
                raise TypeError("MuSiQue answer must be a string.")
            answer = answer_raw.strip()
            if not answer:
                LOGGER.debug("Skipping MuSiQue row %s with empty answer.", row_id)
                continue

            answer_aliases_raw = row.get("answer_aliases", [])
            answer_aliases = _require_sequence(answer_aliases_raw, "answer_aliases")
            gold_answers = [answer]
            for alias_idx, alias_raw in enumerate(answer_aliases):
                if not isinstance(alias_raw, str):
                    raise TypeError(
                        f"MuSiQue answer_aliases[{alias_idx}] must be a string."
                    )
                alias = alias_raw.strip()
                if alias and alias not in gold_answers:
                    gold_answers.append(alias)

            paragraphs = _require_sequence(row["paragraphs"], "paragraphs")
            supporting_passage_ids: list[str] = []
            for list_idx, raw_paragraph in enumerate(paragraphs):
                paragraph = _require_mapping(raw_paragraph, f"paragraphs[{list_idx}]")
                idx_value = paragraph.get("idx")
                if not isinstance(idx_value, int):
                    raise TypeError(f"MuSiQue paragraphs[{list_idx}].idx must be an int.")
                is_supporting = paragraph.get("is_supporting")
                if bool(is_supporting) is not True:
                    continue
                text_value = paragraph.get("paragraph_text")
                if not isinstance(text_value, str):
                    raise TypeError(
                        f"MuSiQue paragraphs[{list_idx}].paragraph_text must be a string."
                    )
                if not text_value.strip():
                    # Mirror iter_passages' empty-text skip. These paragraphs are not
                    # ingested into Qdrant, so their canonical id is not a valid target.
                    continue
                supporting_passage_ids.append(f"musique-{row_id}-{idx_value}")

            if not supporting_passage_ids:
                LOGGER.debug(
                    "Skipping MuSiQue row %s with no usable supporting paragraphs.",
                    row_id,
                )
                continue

            yield MuSiQueGoldQuestion(
                row_id=row_id,
                question=question,
                gold_answers=tuple(gold_answers),
                supporting_passage_ids=tuple(sorted(supporting_passage_ids)),
            )


def _iter_rows_from_hf() -> Iterator[Mapping[str, object]]:
    """Stream raw MuSiQue rows from HuggingFace."""

    from datasets import load_dataset

    rows = load_dataset(
        _HF_DATASET_NAME,
        _HF_DATASET_CONFIG,
        split=_HF_DATASET_SPLIT,
        streaming=True,
    )
    for row in rows:
        yield _require_mapping(row, "row")


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MuSiQue {field_name} must be a mapping.")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError(f"MuSiQue {field_name} must be a non-string sequence.")
    return value
