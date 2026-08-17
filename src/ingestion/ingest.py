"""Ingest one or all PDF corpora into separate PGVector collections."""

from __future__ import annotations

import argparse
import time

from langchain_core.embeddings import Embeddings

from src.config import CORPUS_NAMES, IngestSettings
from src.common.embedding_factory import create_embeddings
from src.common.vector_store import check_database, count_collection_rows, rebuild_collection
from src.ingestion.pdf_pipeline import discover_pdfs, load_pdf_pages, split_pages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        choices=(*CORPUS_NAMES, "all"),
        default="guides",
        help="적재할 문서 그룹입니다. all은 세 그룹을 순차 처리합니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="PDF 로딩과 청킹까지만 수행하고 임베딩·DB 적재는 생략합니다.",
    )
    return parser.parse_args()


def selected_corpora(name: str) -> tuple[str, ...]:
    return CORPUS_NAMES if name == "all" else (name,)


def prepare_corpus(settings: IngestSettings):
    """Load and split one corpus without touching the vector database."""
    corpus = settings.corpus
    started = time.perf_counter()
    pdf_paths = discover_pdfs(corpus.pdf_dir)
    print(f"[discover] corpus={corpus.name}, PDF={len(pdf_paths)}개")
    pages = load_pdf_pages(pdf_paths, settings.project_root, corpus.name)
    chunks, ids = split_pages(pages, corpus.chunk_size, corpus.chunk_overlap)
    print(
        f"[split] corpus={corpus.name}, 텍스트 페이지={len(pages)}개, "
        f"청크={len(chunks)}개 "
        f"(size={corpus.chunk_size}, overlap={corpus.chunk_overlap}, "
        f"elapsed={time.perf_counter() - started:.1f}초)"
    )
    return chunks, ids


def store_corpus(
    settings: IngestSettings,
    embeddings: Embeddings,
    chunks,
    ids,
) -> None:
    """Rebuild one selected collection and verify its stored row count."""
    rebuild_collection(settings, embeddings, chunks, ids)
    stored_rows = count_collection_rows(settings)
    if stored_rows != len(chunks):
        raise RuntimeError(
            f"적재 검증 실패: corpus={settings.corpus.name}, "
            f"생성 청크={len(chunks)}개, DB 저장={stored_rows}개"
        )
    print(
        f"[verify] corpus={settings.corpus.name}, "
        f"collection={settings.collection_name}, stored_chunks={stored_rows}"
    )


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    settings_list = [
        IngestSettings.for_corpus(name) for name in selected_corpora(args.corpus)
    ]
    for settings in settings_list:
        settings.validate()

    embeddings: Embeddings | None = None
    if not args.dry_run:
        check_database(settings_list[0])
        # 모든 컬렉션이 같은 벡터 공간을 사용하도록 모델을 한 번만 초기화한다.
        embeddings = create_embeddings(settings_list[0])

    for settings in settings_list:
        chunks, ids = prepare_corpus(settings)
        if args.dry_run:
            continue
        if embeddings is None:
            raise RuntimeError("임베딩 모델이 초기화되지 않았습니다.")
        store_corpus(settings, embeddings, chunks, ids)

    mode = "dry-run" if args.dry_run else "적재"
    names = ", ".join(settings.corpus.name for settings in settings_list)
    print(
        f"[done] {mode} 완료: corpora={names}, "
        f"elapsed={time.perf_counter() - started:.1f}초"
    )


if __name__ == "__main__":
    main()
