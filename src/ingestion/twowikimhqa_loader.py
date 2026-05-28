"""2WikiMultiHopQA multihop benchmark loader."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence

from src.ingestion.models import Passage

_HF_DATASET_NAME = "voidful/2WikiMultihopQA"
_HF_DATASET_SPLIT = "validation"


class TwoWikiMhqaLoader:
    """Loader for 2WikiMultiHopQA validation passages."""

    _DATASET_NAME = "2wikimhqa"
    _COLLECTION_NAME = "2wikimhqa_passages_qwen3_embed_4b"
    _PASSAGE_COUNT = 430_000

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
        """Iterate one normalized passage per 2WikiMultiHopQA context paragraph."""

        for row in _iter_rows_from_hf():
            row_id = str(row["_id"])
            context = _require_sequence(row["context"], "context")

            for para_idx, raw_paragraph in enumerate(context):
                paragraph = _require_sequence(raw_paragraph, f"context[{para_idx}]")
                if len(paragraph) != 2:
                    raise TypeError(
                        f"2WikiMHQA context[{para_idx}] must contain title and sentences."
                    )

                # Why: Titles may be plain/JSON-quoted; string sentences must be JSON arrays.
                raw_title = paragraph[0]
                if isinstance(raw_title, str):
                    try:
                        decoded_title = json.loads(raw_title)
                    except json.JSONDecodeError:
                        decoded_title = raw_title
                    title = decoded_title if isinstance(decoded_title, str) else raw_title
                else:
                    title = raw_title
                if not isinstance(title, str):
                    raise TypeError(
                        f"2WikiMHQA context[{para_idx}][0] must be a string."
                    )

                raw_sentences = paragraph[1]
                if isinstance(raw_sentences, str):
                    try:
                        sentences_raw = json.loads(raw_sentences)
                    except json.JSONDecodeError as exc:
                        raise TypeError(
                            f"2WikiMHQA context[{para_idx}][1] is not valid JSON: {exc}"
                        ) from exc
                else:
                    sentences_raw = raw_sentences
                sentences = _require_string_sequence(
                    sentences_raw,
                    f"context[{para_idx}][1]",
                )
                text = " ".join(sentences).strip()
                if not text:
                    continue

                title_value = title or None
                yield Passage(
                    passage_id=f"2wikimhqa-{row_id}-{para_idx}",
                    text=text,
                    source=title_value,
                    title=title_value,
                )


def _iter_rows_from_hf() -> Iterator[Mapping[str, object]]:
    """Stream raw 2WikiMultiHopQA rows from HuggingFace."""

    from datasets import load_dataset

    rows = load_dataset(
        _HF_DATASET_NAME,
        split=_HF_DATASET_SPLIT,
        streaming=True,
    )
    for row in rows:
        yield _require_mapping(row, "row")


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"2WikiMHQA {field_name} must be a mapping.")
    return value


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError(f"2WikiMHQA {field_name} must be a non-string sequence.")
    return value


def _require_string_sequence(value: object, field_name: str) -> list[str]:
    sequence = _require_sequence(value, field_name)
    strings: list[str] = []
    for item in sequence:
        if not isinstance(item, str):
            raise TypeError(f"2WikiMHQA {field_name} entries must be strings.")
        strings.append(item)
    return strings
