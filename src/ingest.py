"""Ingest guide PDFs into the PGVector collection."""

from __future__ import annotations

import argparse
import time

from src.config import IngestSettings
from src.embedding_factory import create_embeddings
from src.pdf_pipeline import discover_pdfs, load_pdf_pages, split_pages
from src.vector_store import check_database, count_collection_rows, rebuild_collection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="PDF 로딩과 청킹까지만 수행하고 임베딩·DB 적재는 생략합니다.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = IngestSettings()
    settings.validate()
    started = time.perf_counter()

    pdf_paths = discover_pdfs(settings.pdf_dir)
    print(f"[discover] guides PDF {len(pdf_paths)}개")
    pages = load_pdf_pages(pdf_paths, settings.project_root)
    chunks, ids = split_pages(pages, settings.chunk_size, settings.chunk_overlap)
    print(
        f"[split] 텍스트 페이지 {len(pages)}개 -> 청크 {len(chunks)}개 "
        f"(size={settings.chunk_size}, overlap={settings.chunk_overlap})"
    )

    if args.dry_run:
        print(f"[done] dry-run 완료: {time.perf_counter() - started:.1f}초")
        return

    check_database(settings)
    embeddings = create_embeddings(settings)
    rebuild_collection(settings, embeddings, chunks, ids)
    stored_rows = count_collection_rows(settings)
    if stored_rows != len(chunks):
        raise RuntimeError(
            f"적재 검증 실패: 생성 청크 {len(chunks)}개, DB 저장 {stored_rows}개"
        )
    print(
        f"[verify] collection={settings.collection_name}, "
        f"stored_chunks={stored_rows}"
    )
    print(f"[done] 전체 적재 완료: {time.perf_counter() - started:.1f}초")


if __name__ == "__main__":
    main()
