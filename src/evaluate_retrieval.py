"""Evaluate all retrieval questions with one shared embedding model instance."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import CORPUS_NAMES, PROJECT_ROOT, IngestSettings
from src.embedding_factory import create_embeddings
from src.vector_store import (
    check_database,
    count_collection_rows,
    open_collection,
)


DEFAULT_QUESTIONS = PROJECT_ROOT / "evaluation" / "retrieval_questions.jsonl"
DEFAULT_RESULTS = PROJECT_ROOT / "evaluation" / "retrieval_results.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "evaluation" / "retrieval_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


def load_questions(path: Path) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            question = json.loads(line)
            required = {
                "id",
                "corpus",
                "question",
                "expected_sources",
                "minimum_source_hits",
                "top_k",
            }
            missing = required - question.keys()
            if missing:
                raise ValueError(
                    f"질문 파일 {line_number}행에 필드가 없습니다: {sorted(missing)}"
                )
            if question["corpus"] not in CORPUS_NAMES:
                raise ValueError(
                    f"질문 {question['id']}의 corpus가 잘못됐습니다: "
                    f"{question['corpus']}"
                )
            questions.append(question)

    if not questions:
        raise ValueError(f"평가 질문이 없습니다: {path}")
    ids = [question["id"] for question in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("평가 질문 ID가 중복됐습니다.")
    return questions


def clean_preview(text: str, limit: int = 240) -> str:
    return " ".join(text.split())[:limit]


def evaluate_question(question: dict[str, Any], store) -> dict[str, Any]:
    top_k = int(question["top_k"])
    results = store.similarity_search_with_score(question["question"], k=top_k)
    expected_sources = set(question["expected_sources"])
    retrieved_sources = [
        str(document.metadata.get("source_file", "")) for document, _ in results
    ]
    expected_hits = expected_sources.intersection(retrieved_sources)
    minimum_hits = int(question["minimum_source_hits"])

    first_expected_rank = next(
        (
            rank
            for rank, source in enumerate(retrieved_sources, start=1)
            if source in expected_sources
        ),
        None,
    )
    reciprocal_rank = 0.0 if first_expected_rank is None else 1 / first_expected_rank
    expected_recall = len(expected_hits) / len(expected_sources)

    row: dict[str, Any] = {
        "question_id": question["id"],
        "corpus": question["corpus"],
        "question": question["question"],
        "top_k": top_k,
        "expected_sources": " | ".join(question["expected_sources"]),
        "minimum_source_hits": minimum_hits,
        "expected_source_hits": len(expected_hits),
        "source_hit": int(len(expected_hits) >= minimum_hits),
        "expected_source_recall": round(expected_recall, 4),
        "first_expected_rank": first_expected_rank or "",
        "reciprocal_rank": round(reciprocal_rank, 4),
    }
    for rank in range(1, top_k + 1):
        if rank <= len(results):
            document, distance = results[rank - 1]
            row[f"rank{rank}_source"] = document.metadata.get("source_file", "")
            row[f"rank{rank}_page"] = document.metadata.get("page_number", "")
            row[f"rank{rank}_distance"] = round(float(distance), 6)
            row[f"rank{rank}_preview"] = clean_preview(document.page_content)
        else:
            row[f"rank{rank}_source"] = ""
            row[f"rank{rank}_page"] = ""
            row[f"rank{rank}_distance"] = ""
            row[f"rank{rank}_preview"] = ""
    return row


def calculate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    passed = sum(int(row["source_hit"]) for row in rows)
    return {
        "questions": count,
        "source_hit_passes": passed,
        "source_hit_rate": round(passed / count, 4),
        "mean_expected_source_recall": round(
            sum(float(row["expected_source_recall"]) for row in rows) / count,
            4,
        ),
        "mean_reciprocal_rank": round(
            sum(float(row["reciprocal_rank"]) for row in rows) / count,
            4,
        ),
    }


def write_results(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "overall": calculate_metrics(rows),
        "by_corpus": {
            corpus: calculate_metrics(
                [row for row in rows if row["corpus"] == corpus]
            )
            for corpus in CORPUS_NAMES
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return summary


def main() -> None:
    args = parse_args()
    questions = load_questions(args.questions)
    used_corpora = tuple(
        corpus
        for corpus in CORPUS_NAMES
        if any(question["corpus"] == corpus for question in questions)
    )
    settings_by_corpus = {
        corpus: IngestSettings.for_corpus(corpus) for corpus in used_corpora
    }
    for settings in settings_by_corpus.values():
        settings.validate()

    first_settings = settings_by_corpus[used_corpora[0]]
    check_database(first_settings)
    for settings in settings_by_corpus.values():
        stored_rows = count_collection_rows(settings)
        if stored_rows <= 0:
            raise RuntimeError(
                f"비어 있거나 없는 컬렉션입니다: {settings.collection_name}"
            )

    embeddings = create_embeddings(first_settings)
    stores = {
        corpus: open_collection(settings, embeddings)
        for corpus, settings in settings_by_corpus.items()
    }

    rows: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        row = evaluate_question(question, stores[question["corpus"]])
        rows.append(row)
        status = "PASS" if row["source_hit"] else "FAIL"
        print(
            f"[{index:02d}/{len(questions)}] {question['id']} "
            f"corpus={question['corpus']} source_hit={status} "
            f"first_expected_rank={row['first_expected_rank'] or '-'}"
        )

    write_results(args.results, rows)
    summary = write_summary(args.summary, rows)
    overall = summary["overall"]
    print(
        f"[done] questions={overall['questions']}, "
        f"passes={overall['source_hit_passes']}, "
        f"source_hit_rate={overall['source_hit_rate']:.1%}, "
        f"mrr={overall['mean_reciprocal_rank']:.4f}"
    )
    print(f"[output] results={args.results}")
    print(f"[output] summary={args.summary}")


if __name__ == "__main__":
    main()
