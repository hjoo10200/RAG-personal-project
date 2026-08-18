"""Retrieve report evidence by fusing PGVector and Elasticsearch ranks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from langchain_core.documents import Document

from src.common.elasticsearch_store import (
    count_index_documents,
    create_elasticsearch_client,
    search_keyword_queries,
)
from src.common.embedding_factory import create_embeddings
from src.common.vector_store import (
    check_database,
    count_collection_rows,
    open_collection,
)
from src.config import CORPUS_NAMES, ElasticsearchSettings, IngestSettings
from src.generation.report_schema import GenerationRequest, RetrievedEvidence, UserSituation
from src.retrieval.keyword_query_builder import build_structured_keyword_queries
from src.retrieval.rag_pipeline import build_search_queries


RRF_CONSTANT = 60
CHANNEL_WEIGHTS = {
    "guides": {"vector": 0.6, "keyword": 0.4},
    "cases": {"vector": 0.6, "keyword": 0.4},
    # Policy eligibility depends heavily on exact names, regions and status terms.
    "policies": {"vector": 0.45, "keyword": 0.55},
}
VECTOR_CANDIDATES_PER_QUERY = 6
KEYWORD_CANDIDATES_PER_QUERY = 8
CHANNEL_CANDIDATE_LIMIT = 12
MAX_CHARS_PER_CHUNK = 400
MAX_RESULTS_PER_CORPUS = {
    "guides": 4,
    "cases": 3,
    "policies": 4,
}


@dataclass
class ChannelCandidate:
    """One chunk after fusion inside a single retrieval channel."""

    document: Document
    score: float = 0.0
    matched_queries: list[str] = field(default_factory=list)


@dataclass
class HybridCandidate:
    """One chunk after weighted rank fusion across both retrieval channels."""

    corpus: str
    document: Document
    hybrid_score: float = 0.0
    retrieval_methods: set[str] = field(default_factory=set)
    matched_queries: list[str] = field(default_factory=list)


def _document_key(document: Document) -> str:
    metadata = document.metadata
    chunk_id = str(metadata.get("chunk_id", "")).strip()
    if chunk_id:
        return chunk_id
    normalized = " ".join(document.page_content.split())
    return (
        f"{metadata.get('corpus', '')}:"
        f"{metadata.get('source_file', '')}:"
        f"{metadata.get('page_number', '')}:"
        f"{normalized[:240]}"
    )


def _trim_content(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= MAX_CHARS_PER_CHUNK:
        return normalized
    boundary = normalized[:MAX_CHARS_PER_CHUNK].rsplit(" ", 1)[0]
    return f"{boundary}…"


def _append_query(queries: list[str], query: str) -> None:
    if query not in queries:
        queries.append(query)


def _retrieve_vector_channel(
    corpus: str,
    queries: tuple[str, ...],
    store: object,
) -> list[ChannelCandidate]:
    """Fuse semantic ranks from multiple corpus-specific queries."""
    candidates: dict[str, ChannelCandidate] = {}
    for query in queries:
        hits = store.similarity_search_with_score(
            query,
            k=VECTOR_CANDIDATES_PER_QUERY,
        )
        for rank, (document, _distance) in enumerate(hits, start=1):
            key = _document_key(document)
            candidate = candidates.setdefault(
                key,
                ChannelCandidate(document=document),
            )
            candidate.score += 1.0 / (RRF_CONSTANT + rank)
            _append_query(candidate.matched_queries, query)
    return sorted(
        candidates.values(),
        key=lambda candidate: (-candidate.score, _document_key(candidate.document)),
    )[:CHANNEL_CANDIDATE_LIMIT]


def _retrieve_keyword_channel(
    corpus: str,
    queries: tuple[str, ...],
    client: object,
    settings: ElasticsearchSettings,
) -> list[ChannelCandidate]:
    """Use the existing structured BM25 multi-query fusion as one channel."""
    hits = search_keyword_queries(
        client,
        settings.index_name(corpus),
        queries,
        k=CHANNEL_CANDIDATE_LIMIT,
        candidates_per_query=KEYWORD_CANDIDATES_PER_QUERY,
        rrf_constant=RRF_CONSTANT,
        max_per_source=2,
    )
    return [
        ChannelCandidate(
            document=hit.document,
            score=hit.rrf_score,
            matched_queries=list(hit.matched_queries),
        )
        for hit in hits
    ]


def _fuse_channels(
    corpus: str,
    vector_candidates: list[ChannelCandidate],
    keyword_candidates: list[ChannelCandidate],
) -> list[HybridCandidate]:
    """Apply weighted RRF to channel ranks instead of incomparable raw scores."""
    fused: dict[str, HybridCandidate] = {}
    weights = CHANNEL_WEIGHTS[corpus]
    channels = (
        ("vector", weights["vector"], vector_candidates),
        ("keyword", weights["keyword"], keyword_candidates),
    )
    for method, weight, candidates in channels:
        for rank, channel_candidate in enumerate(candidates, start=1):
            key = _document_key(channel_candidate.document)
            candidate = fused.setdefault(
                key,
                HybridCandidate(
                    corpus=corpus,
                    document=channel_candidate.document,
                ),
            )
            candidate.hybrid_score += weight / (RRF_CONSTANT + rank)
            candidate.retrieval_methods.add(method)
            for query in channel_candidate.matched_queries:
                _append_query(candidate.matched_queries, query)
    return sorted(
        fused.values(),
        key=lambda candidate: (
            -candidate.hybrid_score,
            -len(candidate.retrieval_methods),
            _document_key(candidate.document),
        ),
    )


def _select_diverse_candidates(
    candidates: list[HybridCandidate],
    limit: int,
) -> list[HybridCandidate]:
    """Avoid repeated chunks while retaining useful sections from the same PDF."""
    selected: list[HybridCandidate] = []
    selected_keys: set[str] = set()
    selected_sources: set[str] = set()
    selected_pages: set[tuple[str, int]] = set()

    # First give different source documents a chance to contribute.
    for candidate in candidates:
        metadata = candidate.document.metadata
        source = str(metadata.get("source_file", ""))
        if not source or source in selected_sources:
            continue
        selected.append(candidate)
        selected_keys.add(_document_key(candidate.document))
        selected_sources.add(source)
        selected_pages.add((source, int(metadata.get("page_number", 0))))
        if len(selected) == limit:
            return selected

    # Then allow another section from a selected PDF, but not the same page.
    for candidate in candidates:
        metadata = candidate.document.metadata
        key = _document_key(candidate.document)
        page_key = (
            str(metadata.get("source_file", "")),
            int(metadata.get("page_number", 0)),
        )
        if key in selected_keys or page_key in selected_pages:
            continue
        selected.append(candidate)
        selected_keys.add(key)
        selected_pages.add(page_key)
        if len(selected) == limit:
            return selected

    return selected


def retrieve_hybrid_evidence(situation: UserSituation) -> GenerationRequest:
    """Search all corpora with both engines and return grounded report evidence."""
    settings_by_corpus = {
        name: IngestSettings.for_corpus(name) for name in CORPUS_NAMES
    }
    for settings in settings_by_corpus.values():
        settings.validate()
        if count_collection_rows(settings) <= 0:
            raise RuntimeError(
                f"PGVector 컬렉션이 비어 있습니다: {settings.collection_name}"
            )

    first_settings = settings_by_corpus[CORPUS_NAMES[0]]
    check_database(first_settings)
    embeddings = create_embeddings(first_settings)

    elasticsearch_settings = ElasticsearchSettings()
    elasticsearch_settings.validate()
    elasticsearch_client = create_elasticsearch_client(elasticsearch_settings)
    for corpus in CORPUS_NAMES:
        index_name = elasticsearch_settings.index_name(corpus)
        if count_index_documents(elasticsearch_client, index_name) <= 0:
            raise RuntimeError(f"Elasticsearch 인덱스가 비어 있습니다: {index_name}")

    vector_queries = build_search_queries(situation)
    keyword_queries = build_structured_keyword_queries(situation)
    selected: list[HybridCandidate] = []

    for corpus in CORPUS_NAMES:
        store = open_collection(settings_by_corpus[corpus], embeddings)
        vector_candidates = _retrieve_vector_channel(
            corpus,
            vector_queries[corpus],
            store,
        )
        keyword_candidates = _retrieve_keyword_channel(
            corpus,
            keyword_queries[corpus],
            elasticsearch_client,
            elasticsearch_settings,
        )
        fused = _fuse_channels(corpus, vector_candidates, keyword_candidates)
        if corpus == "policies":
            # A semantic resemblance alone is not enough to recommend a policy.
            # Keep policies anchored to region/status-aware structured BM25 queries.
            keyword_anchored = [
                candidate
                for candidate in fused
                if "keyword" in candidate.retrieval_methods
            ]
            if keyword_anchored:
                fused = keyword_anchored
        selected.extend(
            _select_diverse_candidates(fused, MAX_RESULTS_PER_CORPUS[corpus])
        )

    evidence: list[RetrievedEvidence] = []
    for candidate in selected:
        metadata = candidate.document.metadata
        source_file = str(metadata.get("source_file", "")).strip()
        page_number = int(metadata.get("page_number", 0))
        if not source_file or page_number <= 0:
            raise ValueError(
                "검색된 Hybrid 문서에 source_file 또는 page_number가 없습니다."
            )
        evidence.append(
            RetrievedEvidence(
                corpus=candidate.corpus,
                source_file=source_file,
                page_number=page_number,
                content=_trim_content(candidate.document.page_content),
                retrieval_methods=sorted(candidate.retrieval_methods),
                hybrid_score=round(candidate.hybrid_score, 8),
                matched_queries=candidate.matched_queries,
            )
        )

    if not evidence:
        raise RuntimeError("Hybrid 검색에서 보고서 생성에 사용할 근거를 찾지 못했습니다.")
    return GenerationRequest(situation=situation, retrieved_context=evidence)
