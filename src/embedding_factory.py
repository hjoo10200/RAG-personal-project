"""Embedding model construction."""

from __future__ import annotations

from langchain_huggingface import HuggingFaceEmbeddings

from src.config import IngestSettings


def create_embeddings(settings: IngestSettings) -> HuggingFaceEmbeddings:
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[embedding] model={settings.embedding_model}, "
        f"device={settings.embedding_device}, batch={settings.embedding_batch_size}"
    )
    return HuggingFaceEmbeddings(
        model_name=settings.embedding_model,
        cache_folder=str(settings.model_cache_dir),
        model_kwargs={
            "device": settings.embedding_device,
            "trust_remote_code": True,
        },
        encode_kwargs={
            "normalize_embeddings": True,
            "batch_size": settings.embedding_batch_size,
            "prompt": "passage: ",
        },
        query_encode_kwargs={
            "normalize_embeddings": True,
            "batch_size": settings.embedding_batch_size,
            "prompt": "query: ",
        },
        show_progress=True,
    )
