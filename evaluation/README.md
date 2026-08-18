# 검색 평가 질문 사용법

`retrieval_questions.jsonl`은 현재 PDF 17개의 Vector 검색 품질을 확인하기 위한 초기 평가 세트다.

2026-08-17 Vector-only 최초 결과는 `baselines/vector_only_2026-08-17/`에 질문과 함께 복사하여 보존했다. 이후 Elasticsearch와 Hybrid 평가 결과는 이 기준선 파일을 덮어쓰지 않는다.

## 구성

- `guides`: G01~G05, 5개
- `cases`: C01~C05, 5개
- `policies`: P01~P05, 5개
- 전체: 15개

각 JSON 행의 필드는 다음 의미다.

| 필드 | 의미 |
|---|---|
| `id` | 질문 고유 번호 |
| `corpus` | 검색할 컬렉션 |
| `question` | 실제 검색에 넣을 사용자형 질문 |
| `expected_sources` | Top-K에서 기대하는 PDF |
| `minimum_source_hits` | 기대 PDF 중 최소 적중 개수 |
| `expected_concepts` | 검색 청크가 포함해야 하는 핵심 근거 |
| `top_k` | 현재 평가할 검색 결과 개수 |

정책 질문은 2026년 최초 구현용 스냅샷을 대상으로 한다. 서비스 응답 단계에서는 공고의 현재 유효성을 별도로 확인해야 한다.

## 수동 실행

프로젝트 루트에서 질문의 `corpus`와 `question`을 다음 명령에 넣는다.

```powershell
.venv\Scripts\python.exe -m src.retrieval.search "질문 내용" --corpus guides -k 3
```

예시:

```powershell
.venv\Scripts\python.exe -m src.retrieval.search "이사업체를 처음 고를 때 방문견적과 계약서에서 무엇을 비교해야 하나요?" --corpus guides -k 3
```

## 전체 자동 실행

15개 질문을 한 번에 실행하려면 프로젝트 루트에서 다음 명령을 사용한다.

```powershell
.venv\Scripts\python.exe -m src.retrieval.evaluate_retrieval
```

임베딩 모델과 세 PGVector 컬렉션 연결을 한 번씩만 초기화한 뒤 모든 질문을 처리한다. 결과는 다음 파일에 저장된다.

- `evaluation/retrieval_results.csv`: 질문별 상위 문서·페이지·거리·본문 미리보기
- `evaluation/retrieval_summary.json`: 전체 및 corpus별 Source Hit, 기대 문서 회수율, MRR

자동 평가는 기대 PDF의 검색 순위만 채점한다. 청크가 실제 답변 근거를 충분히 포함하는지는 CSV의 `rankN_preview`를 읽고 아래의 0~2점 기준으로 별도 판정한다.

## 질문별 판정

각 질문은 다음 순서로 평가한다.

1. 상위 3개 결과에서 `expected_sources`가 `minimum_source_hits` 이상 등장했는지 확인한다.
2. 반환된 청크 본문에 `expected_concepts` 중 실제 답변 근거가 포함됐는지 읽는다.
3. 관련 문서가 있어도 청크가 너무 짧거나 문맥이 끊기면 근거 점수를 낮춘다.

권장 점수는 다음과 같다.

| 점수 | 기준 |
|---:|---|
| 2 | 기대 문서가 검색되고, 청크만으로 질문에 답할 핵심 근거가 충분함 |
| 1 | 기대 문서는 검색됐지만 근거가 일부만 있거나 문맥이 끊김 |
| 0 | 기대 문서가 없거나 질문과 무관한 청크만 검색됨 |

## 전체 기준선

- `Source Hit@3`: 기대 문서 최소 적중 조건을 만족한 질문 비율
- `Evidence Pass@3`: 근거 점수가 1점 이상인 질문 비율
- `Strong Evidence@3`: 근거 점수가 2점인 질문 비율

초기 목표는 다음과 같이 둔다.

```text
Source Hit@3      >= 80%
Evidence Pass@3  >= 80%
Strong Evidence@3 >= 60%
```

15개 질문에서는 각각 다음 개수에 해당한다.

- 80%: 12개 이상
- 60%: 9개 이상

기준에 미달하면 곧바로 LLM 프롬프트를 수정하지 말고 먼저 실패 원인을 `문서 누락`, `청킹`, `임베딩`, `검색 개수`, `질문과 문서의 표현 차이`로 구분한다.
