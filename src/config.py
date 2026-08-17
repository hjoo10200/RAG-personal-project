"""Environment-backed configuration for ingestion and retrieval."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

CORPUS_NAMES = ("guides", "cases", "policies")


@dataclass(frozen=True)
class CorpusConfig:
    """Settings that differ for each knowledge-base corpus."""

    name: str
    pdf_dir: Path
    collection_name: str
    chunk_size: int
    chunk_overlap: int

    def validate(self) -> None:
        if self.name not in CORPUS_NAMES:
            raise ValueError(f"지원하지 않는 corpus입니다: {self.name}")
        if not self.pdf_dir.is_dir():
            raise FileNotFoundError(f"PDF 디렉터리가 없습니다: {self.pdf_dir}")
        if self.chunk_size <= 0:
            raise ValueError(f"{self.name}의 chunk_size는 1 이상이어야 합니다.")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError(
                f"{self.name}의 chunk_overlap은 0 이상 chunk_size 미만이어야 합니다."
            )


def get_corpus_config(name: str) -> CorpusConfig:
    """Build one corpus configuration, allowing per-corpus env overrides."""
    if name not in CORPUS_NAMES:
        raise ValueError(f"지원하지 않는 corpus입니다: {name}")

    defaults = {
        "guides": ("youth_independence_guides", 800, 120),
        "cases": ("youth_independence_cases", 1000, 150),
        "policies": ("youth_independence_policies", 900, 150),
    }
    default_collection, default_size, default_overlap = defaults[name]
    prefix = name.upper()

    # 기존 guides 전용 환경변수와의 호환성을 유지한다.
    collection_fallback = (
        os.getenv("GUIDES_COLLECTION", default_collection)
        if name == "guides"
        else default_collection
    )
    size_fallback = (
        os.getenv("CHUNK_SIZE", str(default_size))
        if name == "guides"
        else str(default_size)
    )
    overlap_fallback = (
        os.getenv("CHUNK_OVERLAP", str(default_overlap))
        if name == "guides"
        else str(default_overlap)
    )

    return CorpusConfig(
        name=name,
        pdf_dir=PROJECT_ROOT / "knowledge_base" / "pdfs" / name,
        collection_name=os.getenv(f"{prefix}_COLLECTION", collection_fallback),
        chunk_size=int(os.getenv(f"{prefix}_CHUNK_SIZE", size_fallback)),
        chunk_overlap=int(
            os.getenv(f"{prefix}_CHUNK_OVERLAP", overlap_fallback)
        ),
    )


@dataclass(frozen=True)
class IngestSettings:
    """Shared runtime settings plus one selected corpus."""

    corpus: CorpusConfig = field(default_factory=lambda: get_corpus_config("guides"))
    project_root: Path = PROJECT_ROOT
    model_cache_dir: Path = PROJECT_ROOT / "models"
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL", "intfloat/multilingual-e5-small"
    )
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu")
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "8"))
    database_url: str = os.getenv(
        "PGVECTOR_URL",
        "postgresql+psycopg://admin:admin123@localhost:5432/vectordb",
    )

    @classmethod
    def for_corpus(cls, name: str) -> IngestSettings:
        return cls(corpus=get_corpus_config(name))

    @property
    def pdf_dir(self) -> Path:
        return self.corpus.pdf_dir

    @property
    def collection_name(self) -> str:
        return self.corpus.collection_name

    @property
    def chunk_size(self) -> int:
        return self.corpus.chunk_size

    @property
    def chunk_overlap(self) -> int:
        return self.corpus.chunk_overlap

    def validate(self) -> None:
        self.corpus.validate()
        if self.embedding_batch_size <= 0:
            raise ValueError("EMBEDDING_BATCH_SIZE는 1 이상이어야 합니다.")

    @property
    def psycopg_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
