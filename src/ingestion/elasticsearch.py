"""Index the existing PDF chunks into corpus-specific Elasticsearch indices."""

from __future__ import annotations

import argparse
import time

from src.common.elasticsearch_store import (
    count_index_documents,
    create_elasticsearch_client,
    rebuild_keyword_index,
)
from src.config import CORPUS_NAMES, ElasticsearchSettings, IngestSettings
from src.ingestion.pdf_pipeline import discover_pdfs, load_pdf_pages, split_pages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        choices=(*CORPUS_NAMES, "all"),
        default="all",
        help="적재할 문서 그룹입니다. 기본값은 all입니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="PDF 로딩과 청킹까지만 확인하고 Elasticsearch는 변경하지 않습니다.",
    )
    return parser.parse_args()


def selected_corpora(name: str) -> tuple[str, ...]:
    return CORPUS_NAMES if name == "all" else (name,)


def prepare_keyword_corpus(settings: IngestSettings):
    """Build the same PDF chunks without importing an embedding model."""
    corpus = settings.corpus
    pdf_paths = discover_pdfs(corpus.pdf_dir)
    print(f"[discover] corpus={corpus.name}, PDF={len(pdf_paths)}개")
    pages = load_pdf_pages(pdf_paths, settings.project_root, corpus.name)
    chunks, ids = split_pages(pages, corpus.chunk_size, corpus.chunk_overlap)
    print(
        f"[split] corpus={corpus.name}, 텍스트 페이지={len(pages)}개, "
        f"청크={len(chunks)}개 "
        f"(size={corpus.chunk_size}, overlap={corpus.chunk_overlap})"
    )
    return chunks, ids


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    corpus_settings = [
        IngestSettings.for_corpus(name) for name in selected_corpora(args.corpus)
    ]
    for settings in corpus_settings:
        settings.validate()

    es_settings = ElasticsearchSettings()
    es_settings.validate()
    client = None
    if not args.dry_run:
        client = create_elasticsearch_client(es_settings)

    for settings in corpus_settings:
        chunks, ids = prepare_keyword_corpus(settings)
        index_name = es_settings.index_name(settings.corpus.name)
        if args.dry_run:
            print(
                f"[dry-run] corpus={settings.corpus.name}, "
                f"index={index_name}, chunks={len(chunks)}"
            )
            continue
        if client is None:
            raise RuntimeError("Elasticsearch 클라이언트가 초기화되지 않았습니다.")
        indexed = rebuild_keyword_index(client, index_name, chunks, ids)
        stored = count_index_documents(client, index_name)
        if indexed != len(chunks) or stored != len(chunks):
            raise RuntimeError(
                f"Elasticsearch 적재 검증 실패: corpus={settings.corpus.name}, "
                f"chunks={len(chunks)}, bulk={indexed}, stored={stored}"
            )
        print(
            f"[verify] corpus={settings.corpus.name}, index={index_name}, "
            f"stored_chunks={stored}"
        )

    mode = "dry-run" if args.dry_run else "Elasticsearch 적재"
    names = ", ".join(settings.corpus.name for settings in corpus_settings)
    print(
        f"[done] {mode} 완료: corpora={names}, "
        f"elapsed={time.perf_counter() - started:.1f}초"
    )


if __name__ == "__main__":
    main()
