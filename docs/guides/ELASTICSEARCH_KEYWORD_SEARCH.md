# Elasticsearch 키워드 검색 가이드

현재 단계는 기존 PGVector Vector-only 검색을 유지하면서 동일한 PDF 청크를 Elasticsearch에 별도로 적재해 BM25 키워드 검색을 검증하는 단계다. 두 검색 결과의 RRF 결합은 아직 적용하지 않는다.

입력·출력과 내부 파일 호출 순서를 포함한 상세 구현 설명은 [Elasticsearch 키워드 검색 구현 흐름 설명서](../reports/ELASTICSEARCH_KEYWORD_PIPELINE.md)를 참고한다.

## 구조

```text
knowledge_base/pdfs/**/*.pdf
  → 기존 PDF 로딩·청킹 파이프라인 재사용
  → Elasticsearch 코퍼스별 인덱스
  → BM25 키워드 검색
```

Elasticsearch에는 임베딩 벡터를 저장하지 않는다. 벡터 검색은 기존 PGVector가 담당하고 Elasticsearch는 정확한 정책명, 계약 용어, 지역명과 금액 표현을 찾는 역할만 담당한다.

## 1. Elasticsearch 시작

```powershell
cd D:\RAG-personal-project
docker compose up -d elasticsearch
docker compose ps
```

기본 개발 구성은 보안을 비활성화한 `http://localhost:9200` 단일 노드다. 외부 Elasticsearch에서 인증을 사용한다면 `.env`에 `ELASTICSEARCH_USERNAME`과 `ELASTICSEARCH_PASSWORD`를 모두 설정한다.

## 2. 변경 없는 dry-run

```powershell
.venv\Scripts\python.exe -m src.ingestion.elasticsearch --corpus all --dry-run
```

이 명령은 PDF 로딩과 청킹 수만 확인하며 Elasticsearch 인덱스를 변경하지 않는다.

## 3. Elasticsearch 적재

```powershell
.venv\Scripts\python.exe -m src.ingestion.elasticsearch --corpus all
```

생성되는 기본 인덱스는 다음과 같다.

- `youth_independence_guides_keywords`
- `youth_independence_cases_keywords`
- `youth_independence_policies_keywords`

선택한 인덱스는 실행할 때 삭제 후 재생성된다. PGVector 컬렉션에는 영향을 주지 않는다.

## 4. 키워드 검색

```powershell
.venv\Scripts\python.exe -m src.retrieval.keyword_search `
  "서울 청년월세지원 소득 임차 조건" `
  --corpus policies `
  -k 3
```

세 인덱스를 각각 검색하려면 `--corpus all`을 사용한다. 결과에는 BM25 점수, 원본 PDF 파일명, 페이지와 본문 미리보기가 출력된다. BM25 점수는 Elasticsearch 검색 내부의 순위에만 사용하며 PGVector 코사인 거리와 직접 더하지 않는다.

## 5. 키워드 검색 자동 평가

```powershell
.venv\Scripts\python.exe -m src.retrieval.evaluate_keyword_retrieval
```

기존 15개 질문을 사용하지만 Vector-only 결과를 덮어쓰지 않고 다음 경로에 저장한다.

- `evaluation/keyword/retrieval_results.csv`
- `evaluation/keyword/retrieval_summary.json`

이 결과를 `evaluation/baselines/vector_only_2026-08-17/`의 Vector-only 기준선과 비교한다.

## 다음 단계

키워드 검색 결과를 기존 평가 질문으로 확인한 뒤 Vector 순위와 BM25 순위를 RRF로 결합한다. 기준선은 `evaluation/baselines/vector_only_2026-08-17/`에 보존되어 있다.
