"""Run similarity-search smoke tests against one or all corpus collections."""

from __future__ import annotations

import argparse

from src.config import CORPUS_NAMES, IngestSettings
from src.common.embedding_factory import create_embeddings
from src.common.vector_store import check_database, open_collection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="검색할 한국어 질의")
    parser.add_argument(
        "--corpus",
        choices=(*CORPUS_NAMES, "all"),
        default="guides",
        help="검색할 문서 그룹입니다. all은 세 컬렉션을 각각 검색합니다.",
    )
    parser.add_argument("-k", type=int, default=3, help="컬렉션별 반환 청크 수")
    return parser.parse_args()


def selected_corpora(name: str) -> tuple[str, ...]:
    return CORPUS_NAMES if name == "all" else (name,)


def main() -> None:
    args = parse_args()
    if args.k <= 0:
        raise ValueError("k는 1 이상이어야 합니다.")

    settings_list = [
        IngestSettings.for_corpus(name) for name in selected_corpora(args.corpus)
    ]
    for settings in settings_list:
        settings.validate()

    check_database(settings_list[0])
    embeddings = create_embeddings(settings_list[0])

    for settings in settings_list:
        store = open_collection(settings, embeddings)
        results = store.similarity_search_with_score(args.query, k=args.k)
        print(
            f"[search] corpus={settings.corpus.name}, "
            f"collection={settings.collection_name}, "
            f"query={args.query!r}, results={len(results)}"
        )
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
