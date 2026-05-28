"""MuSiQue multihop benchmark loader."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from src.ingestion.models import Passage

_HF_DATASET_NAME = "bdsaglam/musique"
_HF_DATASET_CONFIG = "answerable"
_HF_DATASET_SPLIT = "validation"


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
