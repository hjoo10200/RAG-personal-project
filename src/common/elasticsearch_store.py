"""Elasticsearch client, BM25 index, and keyword-search helpers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from collections import defaultdict
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


@dataclass(frozen=True)
class FusedKeywordSearchHit:
    """One deduplicated result fused from multiple structured keyword queries."""

    document: Document
    rrf_score: float
    best_bm25_score: float
    matched_queries: tuple[str, ...]


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
            "index": {"max_ngram_diff": 13},
            "analysis": {
                "tokenizer": {
                    "korean_ngram_tokenizer": {
                        "type": "ngram",
                        "min_gram": 2,
                        "max_gram": 15,
                        "token_chars": ["letter", "digit"],
                    }
                },
                "analyzer": {
                    "korean_standard": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"],
                    },
                    "korean_ngram": {
                        "type": "custom",
                        "tokenizer": "korean_ngram_tokenizer",
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
                    "fields": {
                        "ngram": {
                            "type": "text",
                            "analyzer": "korean_ngram",
                            "search_analyzer": "korean_standard",
                        }
                    },
                },
                "source_file": {
                    "type": "text",
                    "analyzer": "korean_standard",
                    "fields": {"raw": {"type": "keyword"}},
                },
                "corpus": {"type": "keyword"},
                "page_number": {"type": "integer"},
                "chunk_id": {"type": "keyword"},
                "document_title": {
                    "type": "text",
                    "analyzer": "korean_standard",
                    "fields": {"raw": {"type": "keyword"}},
                },
                "policy_name": {
                    "type": "text",
                    "analyzer": "korean_standard",
                    "fields": {"raw": {"type": "keyword"}},
                },
                "keywords": {
                    "type": "text",
                    "analyzer": "korean_standard",
                },
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
                "document_title": str(metadata.get("document_title", "")),
                "policy_name": str(metadata.get("policy_name", "")),
                "keywords": list(metadata.get("search_keywords", [])),
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
                    "match_phrase": {
                        "document_title": {
                            "query": normalized,
                            "boost": 7.0,
                        }
                    }
                },
                {
                    "match_phrase": {
                        "policy_name": {
                            "query": normalized,
                            "boost": 9.0,
                        }
                    }
                },
                {
                    "multi_match": {
                        "query": normalized,
                        "fields": [
                            "policy_name^8",
                            "document_title^6",
                            "keywords^4",
                            "source_file^2",
                            "content",
                            "content.ngram^0.5",
                        ],
                        "type": "best_fields",
                        "operator": "or",
                        "minimum_should_match": "35%",
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


def search_keyword_queries(
    client: Elasticsearch,
    index_name: str,
    queries: Sequence[str],
    *,
    k: int = 3,
    candidates_per_query: int = 5,
    rrf_constant: int = 60,
    max_per_source: int = 1,
) -> list[FusedKeywordSearchHit]:
    """Search concise subqueries and fuse their ranks without comparing raw scores."""
    normalized_queries = tuple(
        dict.fromkeys(" ".join(query.split()) for query in queries if query.strip())
    )
    if not normalized_queries:
        raise ValueError("하나 이상의 키워드 하위 질의가 필요합니다.")
    if k <= 0 or candidates_per_query <= 0:
        raise ValueError("k와 candidates_per_query는 1 이상이어야 합니다.")
    if rrf_constant < 0:
        raise ValueError("rrf_constant는 0 이상이어야 합니다.")
    if max_per_source <= 0:
        raise ValueError("max_per_source는 1 이상이어야 합니다.")

    scores: dict[str, float] = defaultdict(float)
    best_scores: dict[str, float] = defaultdict(float)
    documents: dict[str, Document] = {}
    matched_queries: dict[str, list[str]] = defaultdict(list)

    for query in normalized_queries:
        hits = search_keyword_index(
            client,
            index_name,
            query,
            k=candidates_per_query,
        )
        for rank, hit in enumerate(hits, start=1):
            metadata = hit.document.metadata
            key = str(metadata.get("chunk_id", "")).strip()
            if not key:
                key = (
                    f"{metadata.get('source_file', '')}:"
                    f"{metadata.get('page_number', '')}:"
                    f"{' '.join(hit.document.page_content.split())[:160]}"
                )
            scores[key] += 1.0 / (rrf_constant + rank)
            best_scores[key] = max(best_scores[key], hit.score)
            documents[key] = hit.document
            if query not in matched_queries[key]:
                matched_queries[key].append(query)

    ranked = sorted(
        scores,
        key=lambda key: (-scores[key], -best_scores[key], key),
    )
    selected: list[str] = []
    source_counts: dict[str, int] = defaultdict(int)
    for key in ranked:
        source = str(documents[key].metadata.get("source_file", ""))
        if source_counts[source] >= max_per_source:
            continue
        selected.append(key)
        source_counts[source] += 1
        if len(selected) == k:
            break
    if len(selected) < k:
        for key in ranked:
            if key in selected:
                continue
            selected.append(key)
            if len(selected) == k:
                break

    return [
        FusedKeywordSearchHit(
            document=documents[key],
            rrf_score=scores[key],
            best_bm25_score=best_scores[key],
            matched_queries=tuple(matched_queries[key]),
        )
        for key in selected
    ]
