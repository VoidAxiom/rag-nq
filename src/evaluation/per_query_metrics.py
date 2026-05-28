"""Per-query answer and evidence metrics for interactive RAG diagnostics."""

from __future__ import annotations

import re
import string
from collections import Counter

_ARTICLES_RE = re.compile(r"\b(a|an|the)\b", flags=re.IGNORECASE)
_PUNCTUATION = set(string.punctuation)


def normalize_answer(answer: str) -> str:
    """Apply SQuAD-style answer normalization."""

    lowered = answer.lower()
    without_punctuation = "".join(char for char in lowered if char not in _PUNCTUATION)
    without_articles = _ARTICLES_RE.sub(" ", without_punctuation)
    return " ".join(without_articles.split())


def compute_em(prediction: str, gold_answers: list[str]) -> float:
    """Return exact match against any normalized gold answer."""

    normalized_prediction = normalize_answer(prediction)
    return float(any(normalized_prediction == normalize_answer(gold) for gold in gold_answers))


def compute_f1(prediction: str, gold_answers: list[str]) -> float:
    """Return the max SQuAD token F1 over normalized gold answers."""

    prediction_tokens = normalize_answer(prediction).split()
    return max(
        (
            _f1_for_tokens(prediction_tokens, normalize_answer(gold).split())
            for gold in gold_answers
        ),
        default=0.0,
    )


def compute_supporting_fact_recall_at_k(
    retrieved_point_ids: list[str], supporting_passage_ids: list[str], k: int
) -> float:
    """Return supporting-passage recall over the first ``k`` retrieved point IDs."""

    supporting_ids = set(supporting_passage_ids)
    if not supporting_ids:
        return 0.0
    retrieved_at_k = set(retrieved_point_ids[: max(k, 0)])
    matched = supporting_ids.intersection(retrieved_at_k)
    return len(matched) / len(supporting_ids)


def _f1_for_tokens(prediction_tokens: list[str], gold_tokens: list[str]) -> float:
    if not prediction_tokens or not gold_tokens:
        return 0.0

    common = Counter(prediction_tokens) & Counter(gold_tokens)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0

    precision = overlap / len(prediction_tokens)
    recall = overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)
