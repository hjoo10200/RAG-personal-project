"""OpenAI embedding model construction."""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from src.config import IngestSettings


def create_embeddings(settings: IngestSettings) -> OpenAIEmbeddings:
    """Create one LangChain OpenAI embedding client without making an API call."""
    if not settings.openai_api_key or settings.openai_api_key.lower().startswith("your_"):
        raise ValueError(
            "OPENAI_API_KEY가 설정되지 않았습니다. .env에 OpenAI API 키를 입력하세요."
        )
    print(
        f"[embedding] model={settings.embedding_model}, "
        f"dimensions={settings.embedding_dimensions}, "
        f"batch={settings.embedding_batch_size}"
    )
    return OpenAIEmbeddings(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        chunk_size=settings.embedding_batch_size,
        timeout=settings.embedding_timeout_seconds,
        max_retries=settings.embedding_max_retries,
        show_progress_bar=True,
    )
