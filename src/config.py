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
    embedding_local_files_only: bool = os.getenv(
        "EMBEDDING_LOCAL_FILES_ONLY", "true"
    ).lower() in {"1", "true", "yes"}
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


@dataclass(frozen=True)
class GenerationSettings:
    """Groq report-generation settings."""

    api_key: str = os.getenv("GROQ_API_KEY", "")
    model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    temperature: float = float(os.getenv("GROQ_TEMPERATURE", "0"))
    max_tokens: int = int(os.getenv("GROQ_MAX_TOKENS", "2000"))
    timeout_seconds: float = float(os.getenv("GROQ_TIMEOUT_SECONDS", "120"))
    max_retries: int = int(os.getenv("GROQ_MAX_RETRIES", "2"))
    reasoning_effort: str = os.getenv("GROQ_REASONING_EFFORT", "low")

    def validate(self) -> None:
        if not self.api_key or self.api_key.lower().startswith("your_"):
            raise ValueError(
                "GROQ_API_KEY가 설정되지 않았습니다. .env에 Groq API 키를 입력하세요."
            )
        if self.model != "openai/gpt-oss-120b":
            raise ValueError(
                "이번 프로젝트의 보고서 생성 모델은 "
                "openai/gpt-oss-120b로 고정합니다."
            )
        if not 0 <= self.temperature <= 2:
            raise ValueError("GROQ_TEMPERATURE는 0 이상 2 이하여야 합니다.")
        if self.max_tokens <= 0:
            raise ValueError("GROQ_MAX_TOKENS는 1 이상이어야 합니다.")
        if self.timeout_seconds <= 0:
            raise ValueError("GROQ_TIMEOUT_SECONDS는 0보다 커야 합니다.")
        if self.max_retries < 0:
            raise ValueError("GROQ_MAX_RETRIES는 0 이상이어야 합니다.")
        if self.reasoning_effort not in {"low", "medium", "high"}:
            raise ValueError(
                "GROQ_REASONING_EFFORT는 low, medium, high 중 하나여야 합니다."
            )


@dataclass(frozen=True)
class ElasticsearchSettings:
    """Elasticsearch keyword-index settings."""

    url: str = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    username: str = os.getenv("ELASTICSEARCH_USERNAME", "")
    password: str = os.getenv("ELASTICSEARCH_PASSWORD", "")
    verify_certs: bool = os.getenv(
        "ELASTICSEARCH_VERIFY_CERTS", "false"
    ).lower() in {"1", "true", "yes"}
    request_timeout: float = float(
        os.getenv("ELASTICSEARCH_REQUEST_TIMEOUT", "30")
    )
    index_prefix: str = os.getenv(
        "ELASTICSEARCH_INDEX_PREFIX", "youth_independence"
    )

    def validate(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(
                "ELASTICSEARCH_URL은 http:// 또는 https://로 시작해야 합니다."
            )
        if bool(self.username) != bool(self.password):
            raise ValueError(
                "Elasticsearch 인증을 사용하려면 username과 password를 모두 설정하세요."
            )
        if self.request_timeout <= 0:
            raise ValueError("ELASTICSEARCH_REQUEST_TIMEOUT은 0보다 커야 합니다.")
        if not self.index_prefix.strip():
            raise ValueError("ELASTICSEARCH_INDEX_PREFIX는 비어 있을 수 없습니다.")

    def index_name(self, corpus: str) -> str:
        if corpus not in CORPUS_NAMES:
            raise ValueError(f"지원하지 않는 corpus입니다: {corpus}")
        return f"{self.index_prefix}_{corpus}_keywords"
