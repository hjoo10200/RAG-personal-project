"""Elasticsearch client, BM25 index, and keyword-search helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from langchain_core.documents import Document

from src.config import ElasticsearchSettings


@dataclass(frozen=True)
class KeywordSearchHit:
    """One Elasticsearch result with its BM25 score."""

    document: Document
    score: float


def create_elasticsearch_client(
    settings: ElasticsearchSettings,
    *,
    check_connection: bool = True,
) -> Elasticsearch:
    """Create one configured client without hard-coded credentials."""
    settings.validate()
    client_kwargs: dict[str, object] = {
        "hosts": [settings.url],
        "verify_certs": settings.verify_certs,
        "request_timeout": settings.request_timeout,
        "max_retries": 3,
        "retry_on_timeout": True,
    }
    if settings.username and settings.password:
        client_kwargs["basic_auth"] = (settings.username, settings.password)
    client = Elasticsearch(**client_kwargs)
    if check_connection and not client.ping():
        raise RuntimeError(
            "Elasticsearch에 연결할 수 없습니다. 컨테이너 상태와 .env 설정을 확인하세요."
        )
    return client


def keyword_index_mapping() -> dict[str, object]:
    """Return a plugin-free mapping suitable for Korean BM25 retrieval."""
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    "korean_standard": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"],
                    }
                }
            }
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "content": {
                    "type": "text",
                    "analyzer": "korean_standard",
                },
                "source_file": {
                    "type": "text",
                    "analyzer": "korean_standard",
                    "fields": {"raw": {"type": "keyword"}},
                },
                "corpus": {"type": "keyword"},
                "page_number": {"type": "integer"},
                "chunk_id": {"type": "keyword"},
                "metadata": {"type": "object", "enabled": False},
            },
        },
    }


def _bulk_actions(
    index_name: str,
    documents: Sequence[Document],
    ids: Sequence[str],
) -> Iterable[dict[str, object]]:
    if len(documents) != len(ids):
        raise ValueError("Elasticsearch 적재 문서 수와 ID 수가 일치하지 않습니다.")
    for document, chunk_id in zip(documents, ids, strict=True):
        metadata = dict(document.metadata)
        yield {
            "_op_type": "index",
            "_index": index_name,
            "_id": chunk_id,
            "_source": {
                "content": document.page_content,
                "source_file": str(metadata.get("source_file", "")),
                "corpus": str(metadata.get("corpus", "")),
                "page_number": int(metadata.get("page_number", 0)),
                "chunk_id": chunk_id,
                "metadata": metadata,
            },
        }


def rebuild_keyword_index(
    client: Elasticsearch,
    index_name: str,
    documents: Sequence[Document],
    ids: Sequence[str],
) -> int:
    """Replace one corpus index and return the number of indexed chunks."""
    if client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
    client.indices.create(index=index_name, **keyword_index_mapping())
    success, _ = bulk(
        client,
        _bulk_actions(index_name, documents, ids),
        raise_on_error=True,
        refresh=False,
    )
    client.indices.refresh(index=index_name)
    return int(success)


def count_index_documents(client: Elasticsearch, index_name: str) -> int:
    if not client.indices.exists(index=index_name):
        return 0
    return int(client.count(index=index_name)["count"])


def build_keyword_query(query: str) -> dict[str, object]:
    """Combine phrase and term matching while retaining Elasticsearch BM25."""
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("키워드 검색어는 비어 있을 수 없습니다.")
    return {
        "bool": {
            "should": [
                {
                    "match_phrase": {
                        "content": {
                            "query": normalized,
                            "boost": 3.0,
                        }
                    }
                },
                {
                    "multi_match": {
                        "query": normalized,
                        "fields": ["source_file^2", "content"],
                        "type": "best_fields",
                        "operator": "or",
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }


def search_keyword_index(
    client: Elasticsearch,
    index_name: str,
    query: str,
    *,
    k: int = 3,
) -> list[KeywordSearchHit]:
    if k <= 0:
        raise ValueError("k는 1 이상이어야 합니다.")
    if not client.indices.exists(index=index_name):
        raise RuntimeError(f"Elasticsearch 인덱스가 없습니다: {index_name}")
    response = client.search(
        index=index_name,
        query=build_keyword_query(query),
        size=k,
        track_total_hits=False,
    )
    hits: list[KeywordSearchHit] = []
    for hit in response["hits"]["hits"]:
        source = hit["_source"]
        metadata = dict(source.get("metadata", {}))
        metadata.update(
            {
                "source_file": source["source_file"],
                "corpus": source["corpus"],
                "page_number": source["page_number"],
                "chunk_id": source["chunk_id"],
            }
        )
        hits.append(
            KeywordSearchHit(
                document=Document(
                    page_content=source["content"],
                    metadata=metadata,
                ),
                score=float(hit["_score"]),
            )
        )
    return hits
