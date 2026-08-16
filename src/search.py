"""Run a small similarity-search smoke test against the guides collection."""

from __future__ import annotations

import argparse

from src.config import IngestSettings
from src.embedding_factory import create_embeddings
from src.vector_store import check_database, open_collection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="검색할 한국어 질의")
    parser.add_argument("-k", type=int, default=3, help="반환할 청크 수")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.k <= 0:
        raise ValueError("k는 1 이상이어야 합니다.")

    settings = IngestSettings()
    settings.validate()
    check_database(settings)
    store = open_collection(settings, create_embeddings(settings))
    results = store.similarity_search_with_score(args.query, k=args.k)

    print(f"[search] query={args.query!r}, results={len(results)}")
    for rank, (document, distance) in enumerate(results, start=1):
        metadata = document.metadata
        preview = " ".join(document.page_content.split())[:180]
        print(
            f"{rank}. distance={distance:.4f} "
            f"source={metadata.get('source_file')} "
            f"page={metadata.get('page_number')}\n   {preview}"
        )


if __name__ == "__main__":
    main()
