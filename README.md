# 청년 자취 독립 플래너 RAG

취업·구직·대학(원) 진학 때문에 처음 자취하는 청년에게 실제 사례, 독립 실행 지식, 지원정책을 근거로 구조화된 리포트를 제공하는 PDF 기반 RAG 프로젝트다.

RAG 적재 대상은 다음 경로의 PDF 17개다.

```text
knowledge_base/pdfs/**/*.pdf
```

세부 문서 구성과 품질 기준은 [`knowledge_base/README.md`](./knowledge_base/README.md)를 참고한다. 현재 적재 대상에서 제외한 이전 자료는 `knowledge_base/archive/`에 보관한다.

## 프로젝트 구조

```text
src/
├─ common/       # 임베딩과 PGVector 공통 연결
├─ ingestion/    # PDF 로딩, 청킹, 벡터 DB 적재
├─ retrieval/    # 검색, 평가, RAG 근거 구성
├─ generation/   # Groq 보고서 생성과 출력 스키마
├─ config.py     # 환경설정
└─ run_rag.py    # 검색부터 보고서 생성까지의 실행 진입점
knowledge_base/  # 원본 PDF, 메타데이터, 보관 자료
evaluation/      # 검색 질문과 평가 결과
examples/inputs/ # 실행 예제 JSON
docs/            # 실행·Git 가이드와 구현 보고서
storage/         # 실행 중 생성되는 결과물
```

## 벡터 DB 적재

PDF는 용도에 따라 `guides`, `cases`, `policies` 세 PGVector 컬렉션으로 분리한다. 직접 실행할 명령과 검증 순서는 [PDF 적재 가이드](docs/guides/CORPUS_INGESTION_GUIDE.md)를 참고한다.

Vector-only 기준선은 `evaluation/baselines/vector_only_2026-08-17/`에 보존되어 있다. 동일한 PDF 청크를 Elasticsearch에 적재하고 BM25 키워드 검색을 시험하는 방법은 [Elasticsearch 키워드 검색 가이드](docs/guides/ELASTICSEARCH_KEYWORD_SEARCH.md)를 참고한다. 현재 실제 보고서 생성 경로는 아직 Vector-only이며 RRF 결합은 다음 단계다.

검색 품질 검증에는 [`evaluation/retrieval_questions.jsonl`](./evaluation/retrieval_questions.jsonl)의 대표 질문 15개와 [`evaluation/retrieval_results.csv`](./evaluation/retrieval_results.csv) 기록 양식을 사용한다.

최초 자동 평가 결과와 실패 원인 분석은 [`evaluation/retrieval_evaluation_report.md`](./evaluation/retrieval_evaluation_report.md)에 기록한다.

## 구조화 보고서 생성

Groq `openai/gpt-oss-120b` 연결과 종합 보고서 JSON 생성의 1단계 시험 방법은 [생성 단계 검증 가이드](docs/guides/GENERATION_STEP_1.md)를 참고한다. 현재 단계는 검색 결과 자동 연결과 HTML/PDF 렌더링 전의 독립 생성 시험이다.

실제 PGVector 검색 결과를 Groq 보고서 생성에 연결하는 전체 RAG 실행 방법은 [실제 RAG 실행 가이드](docs/guides/REAL_RAG_RUN_GUIDE.md)를 참고한다. 이 실행 경로는 `TEST_*` 합성 문서를 사용하지 않는다. 전체 흐름과 입력·출력은 [현재 구현 상세 설명서](docs/IMPLEMENTATION_OVERVIEW.md), 다른 문서 목록은 [문서 인덱스](docs/README.md)에 정리되어 있다.
