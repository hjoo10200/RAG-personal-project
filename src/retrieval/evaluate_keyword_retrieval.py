"""Evaluate Elasticsearch BM25 retrieval without overwriting vector results."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from src.common.elasticsearch_store import (
    count_index_documents,
    create_elasticsearch_client,
    search_keyword_index,
)
from src.config import CORPUS_NAMES, PROJECT_ROOT, ElasticsearchSettings
from src.retrieval.evaluate_retrieval import (
    DEFAULT_QUESTIONS,
    clean_preview,
    load_questions,
    write_results,
    write_summary,
)


DEFAULT_RESULTS = PROJECT_ROOT / "evaluation" / "keyword" / "retrieval_results.csv"
DEFAULT_SUMMARY = PROJECT_ROOT / "evaluation" / "keyword" / "retrieval_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


def evaluate_question(
    question: dict[str, Any],
    client,
    index_name: str,
) -> dict[str, Any]:
    top_k = int(question["top_k"])
    hits = search_keyword_index(
        client,
        index_name,
        question["question"],
        k=top_k,
    )
    expected_sources = set(question["expected_sources"])
    retrieved_sources = [
        str(hit.document.metadata.get("source_file", "")) for hit in hits
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
        if rank <= len(hits):
            hit = hits[rank - 1]
            metadata = hit.document.metadata
            row[f"rank{rank}_source"] = metadata.get("source_file", "")
            row[f"rank{rank}_page"] = metadata.get("page_number", "")
            row[f"rank{rank}_bm25_score"] = round(hit.score, 6)
            row[f"rank{rank}_preview"] = clean_preview(hit.document.page_content)
        else:
            row[f"rank{rank}_source"] = ""
            row[f"rank{rank}_page"] = ""
            row[f"rank{rank}_bm25_score"] = ""
            row[f"rank{rank}_preview"] = ""
    return row


def main() -> None:
    args = parse_args()
    questions = load_questions(args.questions)
    settings = ElasticsearchSettings()
    client = create_elasticsearch_client(settings)
    used_corpora = tuple(
        corpus
        for corpus in CORPUS_NAMES
        if any(question["corpus"] == corpus for question in questions)
    )
    for corpus in used_corpora:
        index_name = settings.index_name(corpus)
        if count_index_documents(client, index_name) <= 0:
            raise RuntimeError(f"비어 있거나 없는 Elasticsearch 인덱스입니다: {index_name}")

    rows: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        row = evaluate_question(
            question,
            client,
            settings.index_name(question["corpus"]),
        )
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
