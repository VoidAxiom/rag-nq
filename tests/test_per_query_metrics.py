from __future__ import annotations

from src.evaluation.per_query_metrics import (
    compute_em,
    compute_f1,
    compute_supporting_fact_recall_at_k,
)


def test_compute_em_exact_match() -> None:
    assert compute_em("Paris", ["Paris"]) == 1.0


def test_compute_em_is_case_insensitive() -> None:
    assert compute_em("paris", ["Paris"]) == 1.0


def test_compute_em_is_punctuation_insensitive() -> None:
    assert compute_em("Paris, France!", ["Paris France"]) == 1.0


def test_compute_em_strips_articles() -> None:
    assert compute_em("the cat", ["cat"]) == 1.0


def test_compute_em_uses_any_gold_answer() -> None:
    assert compute_em("Paris", ["London", "Paris", "Berlin"]) == 1.0


def test_compute_em_mismatch_returns_zero() -> None:
    assert compute_em("Paris", ["London"]) == 0.0


def test_compute_f1_identical_strings_returns_one() -> None:
    assert compute_f1("Paris France", ["Paris France"]) == 1.0


def test_compute_f1_disjoint_strings_returns_zero() -> None:
    assert compute_f1("Paris", ["London"]) == 0.0


def test_compute_f1_partial_overlap_matches_squad_formula() -> None:
    actual = compute_f1("the quick brown fox", ["quick fox jumps"])

    # Normalized pred tokens: quick, brown, fox. Gold: quick, fox, jumps.
    # Overlap = 2, precision = 2 / 3, recall = 2 / 3, F1 = 2 / 3.
    precision = 2 / 3
    recall = 2 / 3
    expected = 2 * precision * recall / (precision + recall)
    assert abs(actual - expected) < 1e-12


def test_compute_f1_multi_gold_takes_max() -> None:
    actual = compute_f1("quick fox", ["whale", "quick red fox"])

    # Best gold has two overlapping tokens. Precision = 2 / 2, recall = 2 / 3.
    precision = 2 / 2
    recall = 2 / 3
    expected = 2 * precision * recall / (precision + recall)
    assert abs(actual - expected) < 1e-12


def test_compute_f1_empty_prediction_and_empty_gold_returns_zero() -> None:
    assert compute_f1("", [""]) == 0.0


def test_compute_f1_empty_prediction_with_non_empty_gold_returns_zero() -> None:
    assert compute_f1("", ["Paris"]) == 0.0


def test_compute_f1_non_empty_prediction_with_empty_gold_returns_zero() -> None:
    assert compute_f1("Paris", [""]) == 0.0


def test_supporting_fact_recall_at_k_all_present_in_top_k() -> None:
    assert (
        compute_supporting_fact_recall_at_k(
            ["passage-1", "passage-2", "passage-3"],
            ["passage-1", "passage-2"],
            2,
        )
        == 1.0
    )


def test_supporting_fact_recall_at_k_partial_fraction() -> None:
    actual = compute_supporting_fact_recall_at_k(
        ["passage-1", "passage-2", "passage-3"],
        ["passage-1", "passage-4"],
        3,
    )

    # One of two supporting passages appears in the retrieved top-k set.
    assert actual == 1 / 2


def test_supporting_fact_recall_at_k_none_in_top_k_returns_zero() -> None:
    assert (
        compute_supporting_fact_recall_at_k(
            ["passage-1", "passage-2"],
            ["passage-3"],
            2,
        )
        == 0.0
    )


def test_supporting_fact_recall_at_k_empty_supporting_ids_returns_zero() -> None:
    assert compute_supporting_fact_recall_at_k(["passage-1"], [], 1) == 0.0


def test_supporting_fact_recall_at_k_larger_than_retrieved_list_size() -> None:
    actual = compute_supporting_fact_recall_at_k(
        ["passage-1"],
        ["passage-1", "passage-2"],
        50,
    )

    # k exceeds retrieved count; one of two supporting passages is present.
    assert actual == 1 / 2
