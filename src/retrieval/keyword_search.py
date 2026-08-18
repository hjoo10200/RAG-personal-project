"""Search one or all Elasticsearch BM25 keyword indices."""

from __future__ import annotations

import argparse

from src.common.elasticsearch_store import (
    count_index_documents,
    create_elasticsearch_client,
    search_keyword_index,
)
from src.config import CORPUS_NAMES, ElasticsearchSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="검색할 한국어 키워드 질의")
    parser.add_argument(
        "--corpus",
        choices=(*CORPUS_NAMES, "all"),
        default="guides",
        help="검색할 Elasticsearch 문서 그룹입니다.",
    )
    parser.add_argument("-k", type=int, default=3, help="인덱스별 반환 청크 수")
    return parser.parse_args()


def selected_corpora(name: str) -> tuple[str, ...]:
    return CORPUS_NAMES if name == "all" else (name,)


def main() -> None:
    args = parse_args()
    if args.k <= 0:
        raise SystemExit("k는 1 이상이어야 합니다.")
    settings = ElasticsearchSettings()
    client = create_elasticsearch_client(settings)

    for corpus in selected_corpora(args.corpus):
        index_name = settings.index_name(corpus)
        stored = count_index_documents(client, index_name)
        if stored <= 0:
            raise SystemExit(f"비어 있거나 없는 Elasticsearch 인덱스입니다: {index_name}")
        hits = search_keyword_index(
            client,
            index_name,
            args.query,
            k=args.k,
        )
        print(
            f"[keyword-search] corpus={corpus}, index={index_name}, "
            f"query={args.query!r}, results={len(hits)}"
        )
        for rank, hit in enumerate(hits, start=1):
            metadata = hit.document.metadata
            preview = " ".join(hit.document.page_content.split())[:180]
            print(
                f"{rank}. bm25_score={hit.score:.4f} "
                f"source={metadata.get('source_file')} "
                f"page={metadata.get('page_number')}\n   {preview}"
            )


if __name__ == "__main__":
    main()
