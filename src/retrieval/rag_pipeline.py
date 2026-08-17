"""Retrieve real PGVector evidence for one youth-independence situation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from langchain_core.documents import Document

from src.config import CORPUS_NAMES, IngestSettings
from src.common.embedding_factory import create_embeddings
from src.common.vector_store import check_database, count_collection_rows, open_collection
from src.generation.report_schema import GenerationRequest, RetrievedEvidence, UserSituation


MAX_CHARS_PER_CHUNK = 450
MAX_RESULTS_PER_CORPUS = {
    "guides": 3,
    "cases": 2,
    "policies": 2,
}


@dataclass(frozen=True)
class SearchHit:
    corpus: str
    query: str
    document: Document
    distance: float


def build_search_queries(situation: UserSituation) -> dict[str, tuple[str, ...]]:
    """Build corpus-specific semantic searches from selected and free-form input."""
    priorities = " ".join(situation.priorities)
    situation_summary = (
        f"{situation.purpose} 독립, {situation.current_region}에서 "
        f"{situation.target_region} 이동, {situation.housing_preference}, "
        f"{situation.move_timeline}, {priorities}, {situation.additional_context}"
    )
    return {
        "guides": (
            f"{situation_summary} 첫 자취 주택 임대차 계약 등기사항 보증금 월세 확인사항",
            f"{situation_summary} 이사 준비 이사업체 견적 이사 당일 전입신고 공과금",
            f"{situation_summary} 청년 자취 초기비용 월 생활비 예산 저축 비상금",
        ),
        "cases": (
            "청년 1인 가구 실제 월평균 생활비 식비 주거비 월세 지출 소득 공백 사례",
            f"{situation.target_region} 취업 통근 주거 선택 청년 원룸 월세 독립 심층면접",
        ),
        "policies": (
            f"2026 {situation.target_region} 청년월세지원 사업 지원대상 신청자격 지원금액 지원기간 모집",
            f"2026 {situation.target_region} 청년 부동산 중개보수 이사비 지원대상 지원금액 주택조건",
        ),
    }


def _document_key(document: Document) -> tuple[str, int, str]:
    metadata = document.metadata
    return (
        str(metadata.get("source_file", "")),
        int(metadata.get("page_number", 0)),
        " ".join(document.page_content.split())[:200],
    )


def _trim_content(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= MAX_CHARS_PER_CHUNK:
        return normalized
    return normalized[:MAX_CHARS_PER_CHUNK].rsplit(" ", 1)[0] + "…"


def _select_diverse_hits(hits: list[SearchHit], limit: int) -> list[SearchHit]:
    """Prefer lower distance while avoiding one PDF monopolizing a corpus."""
    selected: list[SearchHit] = []
    source_counts: dict[str, int] = defaultdict(int)
    seen_documents: set[tuple[str, int, str]] = set()

    for hit in sorted(hits, key=lambda item: item.distance):
        key = _document_key(hit.document)
        source_file = key[0]
        if key in seen_documents or source_counts[source_file] >= 1:
            continue
        selected.append(hit)
        seen_documents.add(key)
        source_counts[source_file] += 1
        if len(selected) == limit:
            break

    if len(selected) < limit:
        for hit in sorted(hits, key=lambda item: item.distance):
            key = _document_key(hit.document)
            if key in seen_documents:
                continue
            selected.append(hit)
            seen_documents.add(key)
            if len(selected) == limit:
                break
    return selected


def retrieve_real_evidence(situation: UserSituation) -> GenerationRequest:
    """Search all real collections and return evidence ready for generation."""
    settings_by_corpus = {
        name: IngestSettings.for_corpus(name) for name in CORPUS_NAMES
    }
    for settings in settings_by_corpus.values():
        settings.validate()
        rows = count_collection_rows(settings)
        if rows <= 0:
            raise RuntimeError(
                f"PGVector 컬렉션이 비어 있습니다: {settings.collection_name}"
            )

    first_settings = settings_by_corpus[CORPUS_NAMES[0]]
    check_database(first_settings)
    embeddings = create_embeddings(first_settings)
    queries = build_search_queries(situation)
    selected_hits: list[SearchHit] = []

    for corpus, corpus_queries in queries.items():
        settings = settings_by_corpus[corpus]
        store = open_collection(settings, embeddings)
        candidates: list[SearchHit] = []
        query_selections: list[SearchHit] = []
        selected_sources: set[str] = set()
        selected_documents: set[tuple[str, int, str]] = set()
        for query in corpus_queries:
            query_hits = [
                SearchHit(
                    corpus=corpus,
                    query=query,
                    document=document,
                    distance=float(distance),
                )
                for document, distance in store.similarity_search_with_score(query, k=4)
            ]
            candidates.extend(query_hits)
            for hit in sorted(query_hits, key=lambda item: item.distance):
                key = _document_key(hit.document)
                if key in selected_documents or key[0] in selected_sources:
                    continue
                query_selections.append(hit)
                selected_documents.add(key)
                selected_sources.add(key[0])
                break

        limit = MAX_RESULTS_PER_CORPUS[corpus]
        selected_hits.extend(query_selections[:limit])
        if len(query_selections) < limit:
            fallback = _select_diverse_hits(candidates, limit)
            for hit in fallback:
                if _document_key(hit.document) in selected_documents:
                    continue
                selected_hits.append(hit)
                selected_documents.add(_document_key(hit.document))
                if len(selected_documents) == limit:
                    break

    evidence: list[RetrievedEvidence] = []
    for hit in selected_hits:
        metadata = hit.document.metadata
        source_file = str(metadata.get("source_file", "")).strip()
        page_number = int(metadata.get("page_number", 0))
        if not source_file or page_number <= 0:
            raise ValueError(
                "검색된 PGVector 문서에 source_file 또는 page_number가 없습니다."
            )
        evidence.append(
            RetrievedEvidence(
                corpus=hit.corpus,
                source_file=source_file,
                page_number=page_number,
                content=_trim_content(hit.document.page_content),
            )
        )

    if not evidence:
        raise RuntimeError("PGVector에서 보고서 생성에 사용할 근거를 찾지 못했습니다.")
    return GenerationRequest(situation=situation, retrieved_context=evidence)
