"""PGVector storage and ingestion verification."""

from __future__ import annotations

from collections.abc import Sequence

import psycopg
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from langchain_postgres.vectorstores import DistanceStrategy

from src.config import IngestSettings


def check_database(settings: IngestSettings) -> None:
    try:
        with psycopg.connect(settings.psycopg_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version()")
                cursor.fetchone()
    except Exception as error:
        raise RuntimeError(
            "PostgreSQL에 연결할 수 없습니다. 먼저 `docker compose up -d`를 실행하고 "
            "DB가 healthy 상태인지 확인하세요."
        ) from error


def rebuild_collection(
    settings: IngestSettings,
    embeddings: Embeddings,
    documents: list[Document],
    ids: Sequence[str],
) -> PGVector:
    # langchain_pg_embedding.id는 컬렉션 내부 키가 아니라 테이블 전체의
    # 기본키다. 같은 PDF 청크를 서로 다른 임베딩 컬렉션에 저장할 때 원본
    # chunk_id를 그대로 사용하면 기존 컬렉션 행이 갱신되고 새 컬렉션은
    # 비게 된다. DB 저장 ID만 컬렉션명으로 구분하고, 검색 결과 결합에
    # 사용하는 metadata["chunk_id"]는 변경하지 않는다.
    storage_ids = [f"{settings.collection_name}:{chunk_id}" for chunk_id in ids]
    return PGVector.from_documents(
        documents=documents,
        embedding=embeddings,
        ids=storage_ids,
        connection=settings.database_url,
        collection_name=settings.collection_name,
        distance_strategy=DistanceStrategy.COSINE,
        pre_delete_collection=True,
        use_jsonb=True,
        create_extension=True,
    )


def open_collection(
    settings: IngestSettings,
    embeddings: Embeddings,
) -> PGVector:
    """Open the existing collection without deleting or rebuilding it."""
    return PGVector(
        embeddings=embeddings,
        connection=settings.database_url,
        collection_name=settings.collection_name,
        distance_strategy=DistanceStrategy.COSINE,
        pre_delete_collection=False,
        use_jsonb=True,
        create_extension=False,
    )


def count_collection_rows(settings: IngestSettings) -> int:
    query = """
        SELECT COUNT(*)
        FROM langchain_pg_embedding AS embedding
        JOIN langchain_pg_collection AS collection
          ON embedding.collection_id = collection.uuid
        WHERE collection.name = %s
    """
    with psycopg.connect(settings.psycopg_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (settings.collection_name,))
            result = cursor.fetchone()
    return int(result[0]) if result else 0
