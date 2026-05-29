"""Evaluation suite domain model and JSON persistence helpers."""

from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.retrieval.qdrant_retrievers import Mode


class SuiteConfig(BaseModel):
    """Retrieval and generation configuration for an evaluation suite."""

    model_config = ConfigDict(extra="forbid")

    benchmark: str
    collection: str
    mode: Mode
    top_k: int
    reranker: str
    generator: str


class DatasetRef(BaseModel):
    """Source dataset identifier for a suite entry."""

    model_config = ConfigDict(extra="forbid")

    benchmark: str
    question_id: str


class SuiteEntry(BaseModel):
    """One question entry inside an evaluation suite."""

    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    gold_answers: list[str] = Field(default_factory=list)
    source: Literal["dataset", "authored"]
    dataset_ref: DatasetRef | None = None
    notes: str | None = None


class EvalSuite(BaseModel):
    """Persisted evaluation suite definition."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    config: SuiteConfig
    entries: list[SuiteEntry] = Field(default_factory=list)


_SAFE_SUITE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def new_suite_id(name: str) -> str:
    """Return a filesystem-safe suite id derived from ``name``."""

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        slug = "suite"
    return f"{slug}-{uuid4().hex[:8]}"


def save_suite(suite: EvalSuite, suites_dir: Path) -> None:
    """Persist one suite using an atomic file replace."""

    path = _required_suite_path(suite.id, suites_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(suite.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def load_suite(suite_id: str, suites_dir: Path) -> EvalSuite | None:
    """Load a suite by id, or return ``None`` if it is absent."""

    path = _optional_suite_path(suite_id, suites_dir)
    if path is None or not path.is_file():
        return None
    return EvalSuite.model_validate_json(path.read_text(encoding="utf-8"))


def list_suites(suites_dir: Path) -> list[EvalSuite]:
    """Return all suites sorted deterministically by suite id."""

    if not suites_dir.is_dir():
        return []
    suites: list[EvalSuite] = []
    for path in suites_dir.glob("*.json"):
        suite = load_suite(path.stem, suites_dir)
        if suite is not None:
            suites.append(suite)
    return sorted(suites, key=lambda suite: suite.id)


def delete_suite(suite_id: str, suites_dir: Path) -> bool:
    """Delete a suite file if it exists."""

    path = _optional_suite_path(suite_id, suites_dir)
    if path is None or not path.is_file():
        return False
    path.unlink()
    return True


def add_entry(
    suite_id: str,
    *,
    question: str,
    gold_answers: list[str] | None = None,
    source: Literal["dataset", "authored"],
    dataset_ref: DatasetRef | None = None,
    notes: str | None = None,
    suites_dir: Path,
) -> EvalSuite | None:
    """Append an entry to a suite and persist the updated suite."""

    suite = load_suite(suite_id, suites_dir)
    if suite is None:
        return None
    existing_ids = {entry.id for entry in suite.entries}
    entry_id = uuid4().hex
    while entry_id in existing_ids:
        entry_id = uuid4().hex
    entry = SuiteEntry(
        id=entry_id,
        question=question,
        gold_answers=list(gold_answers or []),
        source=source,
        dataset_ref=dataset_ref,
        notes=notes,
    )
    updated = suite.model_copy(
        update={
            "entries": [*suite.entries, entry],
            "updated_at": _utc_now(),
        }
    )
    save_suite(updated, suites_dir)
    return updated


def update_entry(
    suite_id: str,
    entry_id: str,
    *,
    question: str | None = None,
    gold_answers: list[str] | None = None,
    source: Literal["dataset", "authored"] | None = None,
    dataset_ref: DatasetRef | None = None,
    notes: str | None = None,
    suites_dir: Path,
) -> EvalSuite | None:
    """Update an existing suite entry and persist the updated suite."""

    suite = load_suite(suite_id, suites_dir)
    if suite is None:
        return None

    found = False
    updated_entries: list[SuiteEntry] = []
    for entry in suite.entries:
        if entry.id != entry_id:
            updated_entries.append(entry)
            continue
        fields = entry.model_dump()
        if question is not None:
            fields["question"] = question
        if gold_answers is not None:
            fields["gold_answers"] = list(gold_answers)
        if source is not None:
            fields["source"] = source
        if dataset_ref is not None:
            fields["dataset_ref"] = dataset_ref
        if notes is not None:
            fields["notes"] = notes
        updated_entries.append(SuiteEntry.model_validate(fields))
        found = True

    if not found:
        return None

    updated = suite.model_copy(
        update={
            "entries": updated_entries,
            "updated_at": _utc_now(),
        }
    )
    save_suite(updated, suites_dir)
    return updated


def delete_entry(suite_id: str, entry_id: str, suites_dir: Path) -> EvalSuite | None:
    """Delete an entry from a suite and persist the updated suite."""

    suite = load_suite(suite_id, suites_dir)
    if suite is None:
        return None

    updated_entries = [entry for entry in suite.entries if entry.id != entry_id]
    if len(updated_entries) == len(suite.entries):
        return None

    updated = suite.model_copy(
        update={
            "entries": updated_entries,
            "updated_at": _utc_now(),
        }
    )
    save_suite(updated, suites_dir)
    return updated


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)  # noqa: UP017


def _optional_suite_path(suite_id: str, suites_dir: Path) -> Path | None:
    if not _SAFE_SUITE_ID_RE.fullmatch(suite_id):
        return None
    return suites_dir / f"{suite_id}.json"


def _required_suite_path(suite_id: str, suites_dir: Path) -> Path:
    path = _optional_suite_path(suite_id, suites_dir)
    if path is None:
        raise ValueError(f"Invalid suite id: {suite_id!r}")
    return path
