"""Environment-backed configuration for the ingestion pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class IngestSettings:
    project_root: Path = PROJECT_ROOT
    pdf_dir: Path = PROJECT_ROOT / "knowledge_base" / "pdfs" / "guides"
    model_cache_dir: Path = PROJECT_ROOT / "models"
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL", "intfloat/multilingual-e5-small"
    )
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu")
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "8"))
    chunk_size: int = int(os.getenv("CHUNK_SIZE", "800"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "120"))
    database_url: str = os.getenv(
        "PGVECTOR_URL",
        "postgresql+psycopg://admin:admin123@localhost:5432/vectordb",
    )
    collection_name: str = os.getenv(
        "GUIDES_COLLECTION", "youth_independence_guides"
    )

    def validate(self) -> None:
        if not self.pdf_dir.is_dir():
            raise FileNotFoundError(f"PDF 디렉터리가 없습니다: {self.pdf_dir}")
        if self.chunk_size <= 0:
            raise ValueError("CHUNK_SIZE는 1 이상이어야 합니다.")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("CHUNK_OVERLAP은 0 이상 CHUNK_SIZE 미만이어야 합니다.")
        if self.embedding_batch_size <= 0:
            raise ValueError("EMBEDDING_BATCH_SIZE는 1 이상이어야 합니다.")

    @property
    def psycopg_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
