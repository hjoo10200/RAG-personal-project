"""PDF discovery, page loading, quality checks, and chunk creation."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def count_nul_characters(value: Any) -> int:
    """Count PostgreSQL-incompatible NUL characters in nested values."""
    if isinstance(value, str):
        return value.count("\x00")
    if isinstance(value, dict):
        return sum(
            count_nul_characters(key) + count_nul_characters(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return sum(count_nul_characters(item) for item in value)
    return 0


def replace_nul_characters(value: Any) -> Any:
    """Replace NUL bytes recursively so text and JSONB are PostgreSQL-safe."""
    if isinstance(value, str):
        return value.replace("\x00", " ")
    if isinstance(value, dict):
        return {
            replace_nul_characters(key): replace_nul_characters(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [replace_nul_characters(item) for item in value]
    if isinstance(value, tuple):
        return tuple(replace_nul_characters(item) for item in value)
    return value


def discover_pdfs(pdf_dir: Path) -> list[Path]:
    pdfs = sorted(path for path in pdf_dir.glob("*.pdf") if path.is_file())
    if not pdfs:
        raise FileNotFoundError(f"적재할 PDF가 없습니다: {pdf_dir}")
    return pdfs


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pdf_pages(
    pdf_paths: list[Path], project_root: Path, corpus_name: str
) -> list[Document]:
    pages: list[Document] = []
    for pdf_path in pdf_paths:
        document_hash = file_sha256(pdf_path)
        loaded = list(PyPDFLoader(str(pdf_path), extract_images=False).lazy_load())
        retained = 0
        nul_replacements = 0
        for page in loaded:
            nul_replacements += count_nul_characters(page.page_content)
            nul_replacements += count_nul_characters(page.metadata)
            content = replace_nul_characters(page.page_content).strip()
            if not content:
                continue
            page.page_content = content
            page.metadata = replace_nul_characters(page.metadata)
            page_index = int(page.metadata.get("page", retained))
            page.metadata.update(
                {
                    "source": pdf_path.relative_to(project_root).as_posix(),
                    "source_file": pdf_path.name,
                    "corpus": corpus_name,
                    "knowledge_role": corpus_name,
                    "document_sha256": document_hash,
                    "page_number": page_index + 1,
                }
            )
            pages.append(page)
            retained += 1
        print(
            f"[load] {pdf_path.name}: 전체 {len(loaded)}쪽, "
            f"텍스트 페이지 {retained}쪽"
        )
        if nul_replacements:
            print(
                f"[sanitize] {pdf_path.name}: "
                f"NUL 문자 {nul_replacements}개를 공백으로 치환"
            )
    return pages


def build_splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=True,
        separators=[
            r"\n#{1,6}\s+",
            r"\n\n+",
            r"\n",
            r"(?<=[.!?])\s+",
            r"(?<=[다요죠음함임])\s+",
            r"\s+",
            "",
        ],
    )


def split_pages(
    pages: list[Document], chunk_size: int, chunk_overlap: int
) -> tuple[list[Document], list[str]]:
    splitter = build_splitter(chunk_size, chunk_overlap)
    chunks = splitter.split_documents(pages)
    ids: list[str] = []
    page_chunk_counts: dict[tuple[str, int], int] = {}

    for chunk in chunks:
        # 로더 이후 다른 전처리 단계에서 들어온 NUL도 저장 전에 차단한다.
        chunk.page_content = replace_nul_characters(chunk.page_content)
        chunk.metadata = replace_nul_characters(chunk.metadata)
        source_file = str(chunk.metadata["source_file"])
        page_number = int(chunk.metadata["page_number"])
        key = (source_file, page_number)
        chunk_index = page_chunk_counts.get(key, 0)
        page_chunk_counts[key] = chunk_index + 1
        normalized = re.sub(r"\s+", " ", chunk.page_content).strip()
        chunk.page_content = normalized
        raw_id = (
            f"{chunk.metadata['corpus']}:{chunk.metadata['document_sha256']}:"
            f"{page_number}:"
            f"{chunk_index}:{normalized}"
        )
        chunk_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        chunk.metadata.update(
            {
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "character_count": len(normalized),
            }
        )
        ids.append(chunk_id)

    return chunks, ids
