"""Streamlit scoreboard page."""

from __future__ import annotations

import streamlit as st

from src.evaluation.scoreboard import ScoreboardRow, load_scoreboard


def render_scoreboard_page() -> None:
    """Render the master scoreboard as a sortable Streamlit dataframe."""

    st.title("Scoreboard")
    scoreboard = load_scoreboard()
    if not scoreboard.rows:
        st.markdown("No scoreboard rows yet. Run an eval to populate.")
        return
    st.dataframe(
        [_row_as_dict(row) for row in scoreboard.rows],
        use_container_width=True,
    )


def _row_as_dict(row: ScoreboardRow) -> dict[str, int | float | str | None]:
    return {
        "phase": row.phase,
        "pipeline": row.pipeline,
        "benchmark": row.benchmark,
        "split": row.split,
        "embedder": row.models.embedder,
        "reranker": row.models.reranker,
        "recall@10": row.retriever_metrics.recall_at_10,
        "mrr@10": row.retriever_metrics.mrr_at_10,
        "f1": row.answer_metrics.f1 if row.answer_metrics is not None else None,
        "faithfulness": (
            row.quality_metrics.faithfulness
            if row.quality_metrics is not None
            else None
        ),
        "latency_p50": row.latency_ms.p50,
        "commit": row.commit_sha[:7],
    }
