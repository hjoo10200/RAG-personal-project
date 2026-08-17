"""Embedding model construction."""

from __future__ import annotations

from langchain_huggingface import HuggingFaceEmbeddings

from src.config import IngestSettings


def resolve_embedding_model(settings: IngestSettings) -> str:
    """Resolve the cached snapshot path when offline-only loading is enabled."""
    if not settings.embedding_local_files_only:
        return settings.embedding_model

    repository_dir = settings.model_cache_dir / (
        "models--" + settings.embedding_model.replace("/", "--")
    )
    main_ref = repository_dir / "refs" / "main"
    if not main_ref.is_file():
        raise FileNotFoundError(
            "로컬 임베딩 모델을 찾을 수 없습니다. "
            "EMBEDDING_LOCAL_FILES_ONLY=false로 한 번 다운로드하세요: "
            f"{repository_dir}"
        )
    revision = main_ref.read_text(encoding="utf-8").strip()
    snapshot_dir = repository_dir / "snapshots" / revision
    if not (snapshot_dir / "model.safetensors").is_file():
        raise FileNotFoundError(f"임베딩 모델 스냅샷이 불완전합니다: {snapshot_dir}")
    return str(snapshot_dir)


def create_embeddings(settings: IngestSettings) -> HuggingFaceEmbeddings:
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    model_name = resolve_embedding_model(settings)
    print(
        f"[embedding] model={settings.embedding_model}, "
        f"device={settings.embedding_device}, batch={settings.embedding_batch_size}, "
        f"local_only={settings.embedding_local_files_only}"
    )
    return HuggingFaceEmbeddings(
        model_name=model_name,
        cache_folder=str(settings.model_cache_dir),
        model_kwargs={
            "device": settings.embedding_device,
            "local_files_only": settings.embedding_local_files_only,
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
