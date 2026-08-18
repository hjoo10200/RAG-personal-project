"""Search Elasticsearch using a structured RagRequest instead of one long question."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.common.elasticsearch_store import (
    count_index_documents,
    create_elasticsearch_client,
    search_keyword_queries,
)
from src.config import CORPUS_NAMES, ElasticsearchSettings
from src.generation.report_schema import RagRequest
from src.retrieval.keyword_query_builder import build_structured_keyword_queries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--corpus",
        choices=(*CORPUS_NAMES, "all"),
        default="all",
    )
    parser.add_argument("-k", type=int, default=3, help="코퍼스별 최종 결과 수")
    return parser.parse_args()


def selected_corpora(name: str) -> tuple[str, ...]:
    return CORPUS_NAMES if name == "all" else (name,)


def main() -> None:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.k <= 0:
        raise SystemExit("k는 1 이상이어야 합니다.")

    request = RagRequest.model_validate_json(
        args.input.read_text(encoding="utf-8")
    )
    query_plan = build_structured_keyword_queries(request.situation)
    settings = ElasticsearchSettings()
    client = create_elasticsearch_client(settings)

    for corpus in selected_corpora(args.corpus):
        index_name = settings.index_name(corpus)
        if count_index_documents(client, index_name) <= 0:
            raise SystemExit(f"비어 있거나 없는 Elasticsearch 인덱스입니다: {index_name}")
        queries = query_plan[corpus]
        print(f"[keyword-plan] corpus={corpus}, queries={len(queries)}")
        for number, query in enumerate(queries, start=1):
            print(f"  Q{number}. {query}")
        hits = search_keyword_queries(
            client,
            index_name,
            queries,
            k=args.k,
            candidates_per_query=max(args.k + 2, 5),
            max_per_source=1,
        )
        for rank, hit in enumerate(hits, start=1):
            metadata = hit.document.metadata
            preview = " ".join(hit.document.page_content.split())[:180]
            print(
                f"{rank}. rrf={hit.rrf_score:.6f} "
                f"best_bm25={hit.best_bm25_score:.4f} "
                f"source={metadata.get('source_file')} "
                f"page={metadata.get('page_number')}\n   {preview}"
            )


if __name__ == "__main__":
    main()
