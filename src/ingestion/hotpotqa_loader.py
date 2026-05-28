"""HotpotQA multihop benchmark loader."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from src.ingestion.models import Passage

_HF_DATASET_NAME = "hotpot_qa"
_HF_DATASET_CONFIG = "fullwiki"
_HF_DATASET_SPLIT = "validation"


class HotpotqaLoader:
    """Loader for HotpotQA fullwiki validation passages."""

    _DATASET_NAME = "hotpotqa"
    _COLLECTION_NAME = "hotpotqa_passages_qwen3_embed_4b"
    _PASSAGE_COUNT = 500_000

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
        """Iterate one normalized passage per HotpotQA context paragraph."""

        for row in _iter_rows_from_hf():
            row_id = str(row["id"])
            context = _require_mapping(row["context"], "context")
            titles = _require_string_sequence(context["title"], "context.title")
            sentence_lists = _require_sequence(context["sentences"], "context.sentences")

            for para_idx, (title, raw_sentences) in enumerate(
                zip(titles, sentence_lists, strict=True)
            ):
                sentences = _require_string_sequence(
                    raw_sentences,
                    f"context.sentences[{para_idx}]",
                )
                text = " ".join(sentences).strip()
                if not text:
                    continue

                title_value = title or None
                yield Passage(
                    passage_id=f"hotpotqa-{row_id}-{para_idx}",
                    text=text,
                    source=title_value,
                    title=title_value,
                )


def _iter_rows_from_hf() -> Iterator[Mapping[str, object]]:
    """Stream raw HotpotQA rows from HuggingFace."""

    from datasets import load_dataset

    rows = load_dataset(
        _HF_DATASET_NAME,
        _HF_DATASET_CONFIG,
        split=_HF_DATASET_SPLIT,
        streaming=True,
    )
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("HotpotQA rows must be mappings.")
        yield row


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"HotpotQA {field_name} must be a mapping.")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError(f"HotpotQA {field_name} must be a non-string sequence.")
    return value


def _require_string_sequence(value: object, field_name: str) -> list[str]:
    sequence = _require_sequence(value, field_name)
    strings: list[str] = []
    for item in sequence:
        if not isinstance(item, str):
            raise TypeError(f"HotpotQA {field_name} entries must be strings.")
        strings.append(item)
    return strings
