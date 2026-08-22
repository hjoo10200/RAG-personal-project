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
        "guides": ("youth_independence_guides_openai_3_small", 800, 120),
        "cases": ("youth_independence_cases_openai_3_small", 1000, 150),
        "policies": ("youth_independence_policies_openai_3_small", 900, 150),
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
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL", "text-embedding-3-small"
    )
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    embedding_batch_size: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
    embedding_timeout_seconds: float = float(
        os.getenv("EMBEDDING_TIMEOUT_SECONDS", "120")
    )
    embedding_max_retries: int = int(os.getenv("EMBEDDING_MAX_RETRIES", "3"))
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
        if self.embedding_model != "text-embedding-3-small":
            raise ValueError(
                "이번 프로젝트의 임베딩 모델은 text-embedding-3-small로 고정합니다."
            )
        if self.embedding_dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS는 1 이상이어야 합니다.")
        if self.embedding_batch_size <= 0:
            raise ValueError("EMBEDDING_BATCH_SIZE는 1 이상이어야 합니다.")
        if self.embedding_timeout_seconds <= 0:
            raise ValueError("EMBEDDING_TIMEOUT_SECONDS는 0보다 커야 합니다.")
        if self.embedding_max_retries < 0:
            raise ValueError("EMBEDDING_MAX_RETRIES는 0 이상이어야 합니다.")

    @property
    def psycopg_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@dataclass(frozen=True)
class GenerationSettings:
    """OpenAI report-generation settings."""

    api_key: str = os.getenv("OPENAI_API_KEY", "")
    model: str = os.getenv("OPENAI_GENERATION_MODEL", "gpt-5.4-mini")
    max_tokens: int = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "8000"))
    timeout_seconds: float = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
    max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
    reasoning_effort: str = os.getenv("OPENAI_REASONING_EFFORT", "none")

    def validate(self) -> None:
        if not self.api_key or self.api_key.lower().startswith("your_"):
            raise ValueError(
                "OPENAI_API_KEY가 설정되지 않았습니다. .env에 OpenAI API 키를 입력하세요."
            )
        if self.model != "gpt-5.4-mini":
            raise ValueError(
                "이번 프로젝트의 보고서 생성 모델은 "
                "gpt-5.4-mini로 고정합니다."
            )
        if self.max_tokens <= 0:
            raise ValueError("OPENAI_MAX_OUTPUT_TOKENS는 1 이상이어야 합니다.")
        if self.timeout_seconds <= 0:
            raise ValueError("OPENAI_TIMEOUT_SECONDS는 0보다 커야 합니다.")
        if self.max_retries < 0:
            raise ValueError("OPENAI_MAX_RETRIES는 0 이상이어야 합니다.")
        if self.reasoning_effort not in {"none", "low", "medium", "high", "xhigh"}:
            raise ValueError(
                "OPENAI_REASONING_EFFORT는 none, low, medium, high, xhigh 중 하나여야 합니다."
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
